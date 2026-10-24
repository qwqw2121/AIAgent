import sys
import os
import json
import asyncio
import threading
from datetime import date, datetime
from dotenv import load_dotenv

# 异步 SQLite 相关导入
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv()

from langgraph.graph import StateGraph, END, MessagesState
from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from storage.db import get_connection, report_exists

# LangGraph 的 RetryPolicy / Send 在不同版本里的导入路径不一样，做个兼容兜底。
# 版本较旧时如果这里 import 失败，运行 `pip install -U langgraph` 即可。
try:
    from langgraph.types import RetryPolicy, Send
except ImportError:  # 兼容旧版本 langgraph
    from langgraph.pregel.types import RetryPolicy  # type: ignore
    from langgraph.constants import Send  # type: ignore

# ============================================================
# 1. LLM 配置
# ============================================================
agent_llm = ChatOpenAI(
    model=os.getenv("LLM_MODEL"),
    openai_api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL"),
)

MCP_SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../mcp_server/news_mcp.py")
)

SYSTEM_PROMPT = """你是一个新闻资讯助手。你可以使用工具完成以下任务：
1. search_news_semantic：按主题/问题语义检索新闻库，用于回答资讯类问题，回答时用[序号]标注引用来源；
2. search_news：按关键词/分类精确查询；
3. get_daily_report：读取指定日期(YYYY-MM-DD)的预生成日报；
4. request_daily_report：当 get_daily_report 返回为空、用户又确实需要该日日报时，调用它在后台生成（需要几分钟），并明确告知用户稍后再问一次即可获取。
规则：
- 用户要某天简报：先 get_daily_report，为空再 request_daily_report；
- 用户说"重新/强制生成"时 request_daily_report 的 force 传 true；
- 用户要主题汇总：用 search_news_semantic 检索后自己归纳成文；
- 日期计算以今天 {today} 为准；
- 始终用中文回答。"""


# ============================================================
# 2. 日报生成（本地工具背后：后台线程直调 pipeline）
# ============================================================
BACKGROUND_TASKS: set = set()
_GEN_LOCKS: dict = {}
_GEN_LOCKS_GUARD = threading.Lock()


def _run_daily_flow(report_date: str, force: bool):
    try:
        from pipeline.flows.daily_news_flow import daily_flow

        if not force:  # 幂等：已有日报则跳过
            try:
                conn = get_connection()
                exists = report_exists(conn, report_date)
                conn.close()
                if exists:
                    print(f"🔍 {report_date} 日报已存在，跳过生成")
                    return
            except Exception:
                pass

        target = datetime.strptime(report_date, "%Y-%m-%d").date()
        print(f"🚀 后台启动 daily_flow: {target} (force={force})")
        daily_flow(run_date=target)
        print(f"✅ 日报生成完成: {report_date}")
    except Exception as e:
        print(f"❌ 日报生成失败: {report_date}: {type(e).__name__}: {e}")


async def trigger_report_generation(report_date: str, force: bool = False) -> str:
    """后台触发生成，立即返回状态。同日期幂等（force 除外）。"""
    with _GEN_LOCKS_GUARD:
        lock = _GEN_LOCKS.setdefault(report_date, threading.Lock())

    if not lock.acquire(blocking=False):
        return f"{report_date} 的日报正在生成中，请稍后再查询。"

    def _guarded():
        try:
            _run_daily_flow(report_date, force)
        finally:
            lock.release()

    task = asyncio.create_task(asyncio.to_thread(_guarded))
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(BACKGROUND_TASKS.discard)
    return f"已启动 {report_date} 的日报生成任务（抓取→分析→汇总，预计几分钟）"


@tool
async def request_daily_report(report_date: str, force: bool = False) -> str:
    """当用户需要指定日期(YYYY-MM-DD)的新闻日报/简报，而 get_daily_report 返回内容为空时使用。
    立即返回，实际生成在后台进行，需要几分钟。用户明确要求重新生成时 force 传 true。"""
    return await trigger_report_generation(report_date, force)


# ============================================================
# 3. 工具分组：把"检索类"和"日报类"彻底分开
# ============================================================
# 新工具接入时，只需要在这里登记一下属于哪个组即可；
# 没登记的工具默认归入 SEARCH 组（比默默丢失路由更安全）。
GROUP_SEARCH = "search"
GROUP_REPORT = "report"

TOOL_GROUP_MAP = {
    "search_news_semantic": GROUP_SEARCH,
    "search_news": GROUP_SEARCH,
    "get_daily_report": GROUP_REPORT,
    "request_daily_report": GROUP_REPORT,
}

# 每组独立的超时/重试配置，互不影响，以后要调也只改这一处
GROUP_CONFIG = {
    GROUP_SEARCH: {"timeout_seconds": 20, "retry": RetryPolicy(max_attempts=2)},
    GROUP_REPORT: {"timeout_seconds": 20, "retry": RetryPolicy(max_attempts=1)},
}

TOOLS: list = []            # 全部工具（供 LLM bind_tools 使用）
SEARCH_TOOLS: list = []     # search 组的工具实例
REPORT_TOOLS: list = []     # report 组的工具实例
SYSTEM_MSG = None
app = None


def _split_tools_by_group(all_tools):
    search_tools, report_tools = [], []
    for t in all_tools:
        group = TOOL_GROUP_MAP.get(t.name, GROUP_SEARCH)
        (search_tools if group == GROUP_SEARCH else report_tools).append(t)
    return search_tools, report_tools


# ============================================================
# 4. Agent 节点
# ============================================================
# async def agent_node(state: MessagesState):
#     response = await agent_llm.ainvoke([SYSTEM_MSG] + state["messages"])
#     return {"messages": [response]}
from datetime import datetime, timezone

async def agent_node(state: MessagesState):
    today = datetime.now(timezone.utc).date().isoformat()
    system = SystemMessage(SYSTEM_PROMPT.format(today=today))
    response = await agent_llm.ainvoke([system] + state["messages"])
    return {"messages": [response]}

async def _run_tool_group(state: MessagesState, group_tools: list, group_name: str):
    """只执行属于 group_name 这一组的 tool_calls，独立超时+由节点级 RetryPolicy 负责重试。"""
    last = state["messages"][-1]
    calls = [c for c in (getattr(last, "tool_calls", None) or [])
             if TOOL_GROUP_MAP.get(c["name"], GROUP_SEARCH) == group_name]
    if not calls:
        return {"messages": []}

    node = ToolNode(group_tools)
    # 只把属于本组的 tool_calls 交给 ToolNode，避免和另一组重复执行
    trimmed = AIMessage(content="", tool_calls=calls)
    timeout_seconds = GROUP_CONFIG[group_name]["timeout_seconds"]

    try:
        result = await asyncio.wait_for(
            node.ainvoke({"messages": [trimmed]}), timeout=timeout_seconds
        )
        return result
    except asyncio.TimeoutError:
        print(f"⏱️ [{group_name}] 工具组执行超时（{timeout_seconds}s），涉及 {[c['name'] for c in calls]}")
        # 超时也要给每个 tool_call 一个 ToolMessage 兜底，否则 LLM 侧会因缺少对应回复而报错
        return {
            "messages": [
                ToolMessage(
                    content=f"[{group_name} 工具组执行超时（{timeout_seconds}s），请稍后重试]",
                    tool_call_id=c["id"],
                    name=c["name"],
                )
                for c in calls
            ]
        }


async def tools_search_node(state: MessagesState):
    return await _run_tool_group(state, SEARCH_TOOLS, GROUP_SEARCH)


async def tools_report_node(state: MessagesState):
    return await _run_tool_group(state, REPORT_TOOLS, GROUP_REPORT)


def route_after_agent(state: MessagesState):
    """
    用 recursion_limit（见 build_graph/main 的 config）替代原来手写的
    `len(messages) > 20` 轮数上限——LangGraph 会在超过限制时抛出
    GraphRecursionError，比静默截断更明确、更容易排查。

    这里只负责判断本轮涉及哪些工具组，并用 Send 并行分发：
    如果模型同一轮里既要检索又要读日报，两组会同时跑，不用排队。
    """
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None)
    if not tool_calls:
        return END

    groups_present = {TOOL_GROUP_MAP.get(c["name"], GROUP_SEARCH) for c in tool_calls}
    node_name = {GROUP_SEARCH: "tools_search", GROUP_REPORT: "tools_report"}
    return [Send(node_name[g], state) for g in groups_present]


def build_graph(checkpointer):
    """构建并编译 Graph，接收已经实例化的 checkpointer"""
    g = StateGraph(MessagesState)
    g.add_node("agent", agent_node)
    g.add_node("tools_search", tools_search_node, retry_policy=GROUP_CONFIG[GROUP_SEARCH]["retry"])
    g.add_node("tools_report", tools_report_node, retry_policy=GROUP_CONFIG[GROUP_REPORT]["retry"])

    g.set_entry_point("agent")
    g.add_conditional_edges(
        "agent",
        route_after_agent,
        {"tools_search": "tools_search", "tools_report": "tools_report", END: END},
    )
    g.add_edge("tools_search", "agent")
    g.add_edge("tools_report", "agent")

    # 传入具体的 checkpointer 实例
    return g.compile(checkpointer=checkpointer)


async def _make_async_checkpointer():
    """异步多轮记忆。依赖: pip install langgraph-checkpoint-sqlite aiosqlite
    注意：这里的存储结构（chat_memory.db + MessagesState）完全没变，
    所以昨天及之前的聊天记录/ thread_id 都能正常继续使用，不受本次重构影响。"""
    try:
        db_path = os.path.join(project_root, "chat_memory.db")

        # 1. 建立异步数据库连接 (check_same_thread=False 适配 FastAPI/异步环境)
        conn = await aiosqlite.connect(db_path)

        # 2. 实例化异步 Checkpointer
        saver = AsyncSqliteSaver(conn)

        # 3. 【关键】异步初始化表结构 (首次运行会自动建表)
        await saver.setup()

        return saver
    except ImportError:
        print("⚠️ 未安装 langgraph-checkpoint-sqlite 或 aiosqlite，多轮记忆不可用，使用无记忆模式")
        return None
    except Exception as e:
        print(f"⚠️ 初始化 Checkpointer 失败: {e}，使用无记忆模式")
        return None


# ============================================================
# 5. 独立分析入口（保持原有）
# ============================================================
def run_analyst(title: str, content: str) -> dict:
    from agent.news_analyzer import analyze_news
    return analyze_news(title, content)


# ============================================================
# 6. 初始化 + 测试
# ============================================================
async def init_agent():
    global TOOLS, SEARCH_TOOLS, REPORT_TOOLS, SYSTEM_MSG, agent_llm, app

    client = MultiServerMCPClient({
        "news_mcp": {
            "command": "python",
            "args": [MCP_SCRIPT_PATH],
            "transport": "stdio",
            "env": os.environ.copy(),
        }
    })
    mcp_tools = await client.get_tools()
    TOOLS = list(mcp_tools) + [request_daily_report]
    SEARCH_TOOLS, REPORT_TOOLS = _split_tools_by_group(TOOLS)
    print(f"✅ 加载工具: {[t.name for t in TOOLS]}")
    print(f"   ├─ search 组: {[t.name for t in SEARCH_TOOLS]}")
    print(f"   └─ report 组: {[t.name for t in REPORT_TOOLS]}")

    agent_llm = agent_llm.bind_tools(TOOLS)
    SYSTEM_MSG = SystemMessage(SYSTEM_PROMPT.format(today=date.today().isoformat()))

    # 1. 先异步获取 checkpointer 实例
    checkpointer = await _make_async_checkpointer()

    # 2. 构建并编译 Graph
    app = build_graph(checkpointer)
    return app


async def main():
    print("🚀 启动 Agent (Tool Calling 模式，检索/日报工具组隔离)...\n")
    app_instance = await init_agent()

    # 单轮测试
    tests = [
        "最近有哪些大模型发布的新闻？",
        # "帮我总结一下昨天的重要新闻",
        # "整理一下最近AI芯片行业的进展",
        "帮我生成 2026-09-01 的日报",
    ]

    for q in tests:
        print(f"\n=== 提问: {q} ===")
        try:
            r = await app_instance.ainvoke(
                {"messages": [HumanMessage(content=q)]},
                config={
                    "configurable": {"thread_id": f"test-{hash(q) % 10000}"},
                    # 用官方的 recursion_limit 替代手写的 len(messages) > 20：
                    # 每个 agent<->tools 往返算若干个 step，超限会抛出
                    # GraphRecursionError，而不是被 should_continue 悄悄截断。
                    "recursion_limit": 15,
                },
            )
        except Exception as e:
            # GraphRecursionError 等异常会在这里被捕获，方便你区分
            # “正常没结果” 和 “死循环被熔断” 两种情况
            print(f"❌ 执行失败: {type(e).__name__}: {e}")
            continue

        # 打印回答，限制长度避免刷屏，并加上省略号
        full_answer = r["messages"][-1].content
        print("回答:", full_answer[:400] + ("..." if len(full_answer) > 400 else ""))

    print("\n✅ 所有测试执行完毕！")


if __name__ == "__main__":
    asyncio.run(main())