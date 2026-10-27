import sys
import os
import asyncio
import threading
import time
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from dotenv import load_dotenv

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv()

from langgraph.graph import StateGraph, END, MessagesState
from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    SystemMessage, HumanMessage, AIMessage, ToolMessage, trim_messages,
)
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from storage.db import get_connection, report_exists

try:
    from langgraph.types import RetryPolicy, Send
except ImportError:
    from langgraph.pregel.types import RetryPolicy  # type: ignore
    from langgraph.constants import Send  # type: ignore


# ============================================================
# 1. LLM 配置
# ============================================================
# 改：加超时/重试上限；关闭思考模式（路由+总结不需要推理，能省大量时间）
_base_llm = ChatOpenAI(
    model=os.getenv("LLM_MODEL"),
    openai_api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL"),
    timeout=40,
    max_retries=1,
    streaming=True,
    extra_body={"enable_thinking": False},
)
agent_llm = _base_llm

MCP_SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../mcp_server/news_mcp.py")
)

# 改：明确工具分工、禁止绕路、限制输出长度
SYSTEM_PROMPT = """你是一个新闻资讯助手，今天是 {today}。可用工具：
1. search_news_semantic：按主题/话题/问题做语义检索，资讯类问题的首选；
2. search_news：仅在用户明确指定“分类”或需要精确关键词匹配时使用；
3. get_daily_report：读取指定日期(YYYY-MM-DD)的预生成日报；
4. request_daily_report：get_daily_report 返回为空、用户又确实需要该日日报时，后台生成（需几分钟），并告知用户稍后再问一次。

规则：
- 用户问某个主题/领域的新闻（如“强化学习相关新闻”）：只调用一次 search_news_semantic，拿到结果后直接作答，不要再调用其他工具；
- 同一问题不要重复调用同类工具，不要并行调用多次 search_news；
- 只有用户明确提到“日报/简报”才使用日报相关工具；用户说“重新/强制生成”时 request_daily_report 的 force 传 true；
- 检索结果为空就如实说明，最多再换一次关键词；
- 资讯类回答控制在 300 字以内，列出 3～5 条要点，并用 [序号] 标注来源（有链接时附上）；日报类回答可以更完整；
- 始终用中文回答。"""


# ============================================================
# 2. 日报生成（后台线程直调 pipeline）
# ============================================================
BACKGROUND_TASKS: set = set()
_GEN_LOCKS: dict = {}
_GEN_LOCKS_GUARD = threading.Lock()


def _run_daily_flow(report_date: str, force: bool):
    try:
        from pipeline.flows.daily_news_flow import daily_flow

        if not force:
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
# 3. 工具分组
# ============================================================
GROUP_SEARCH = "search"
GROUP_REPORT = "report"

TOOL_GROUP_MAP = {
    "search_news_semantic": GROUP_SEARCH,
    "search_news": GROUP_SEARCH,
    "get_daily_report": GROUP_REPORT,
    "request_daily_report": GROUP_REPORT,
}

GROUP_CONFIG = {
    GROUP_SEARCH: {"timeout_seconds": 20, "retry": RetryPolicy(max_attempts=2)},
    GROUP_REPORT: {"timeout_seconds": 20, "retry": RetryPolicy(max_attempts=1)},
}

TOOLS: list = []
SEARCH_TOOLS: list = []
REPORT_TOOLS: list = []
app = None
_exit_stack: AsyncExitStack | None = None  # 持有 MCP 持久会话


def _split_tools_by_group(all_tools):
    search_tools, report_tools = [], []
    for t in all_tools:
        group = TOOL_GROUP_MAP.get(t.name, GROUP_SEARCH)
        (search_tools if group == GROUP_SEARCH else report_tools).append(t)
    return search_tools, report_tools


# ============================================================
# 4. Agent 节点
# ============================================================
MAX_HISTORY_MSGS = 16     # 送入 LLM 的最近消息条数
MAX_TOOL_CHARS = 3000     # 历史里单条工具结果的最大字符数


def _shrink(msgs):
    """截断过长的工具返回，防止上下文越滚越大"""
    out = []
    for m in msgs:
        if isinstance(m, ToolMessage):
            text = m.content if isinstance(m.content, str) else str(m.content)
            if len(text) > MAX_TOOL_CHARS:
                m = ToolMessage(
                    content=text[:MAX_TOOL_CHARS] + "…(已截断)",
                    tool_call_id=m.tool_call_id,
                    name=m.name,
                )
        out.append(m)
    return out


async def agent_node(state: MessagesState):
    t0 = time.perf_counter()
    today = datetime.now(timezone.utc).date().isoformat()
    system = SystemMessage(SYSTEM_PROMPT.format(today=today))

    msgs = trim_messages(
        state["messages"],
        strategy="last",
        max_tokens=MAX_HISTORY_MSGS,
        token_counter=len,
        start_on="human",
        include_system=False,
    )
    if not msgs:  # 兜底：本轮消息过多被全部裁掉时，至少保留最后一条
        msgs = state["messages"][-1:]

    response = await agent_llm.ainvoke([system] + _shrink(msgs))
    print(
        f"🧠 agent LLM {time.perf_counter() - t0:.1f}s | "
        f"tool_calls={[c['name'] for c in (response.tool_calls or [])]} | 上下文={len(msgs)}条"
    )
    return {"messages": [response]}


async def _run_tool_group(state: MessagesState, group_tools: list, group_name: str):
    last = state["messages"][-1]
    calls = [c for c in (getattr(last, "tool_calls", None) or [])
             if TOOL_GROUP_MAP.get(c["name"], GROUP_SEARCH) == group_name]
    if not calls:
        return {"messages": []}

    node = ToolNode(group_tools)
    trimmed = AIMessage(content="", tool_calls=calls)
    timeout_seconds = GROUP_CONFIG[group_name]["timeout_seconds"]
    t0 = time.perf_counter()

    try:
        result = await asyncio.wait_for(
            node.ainvoke({"messages": [trimmed]}), timeout=timeout_seconds
        )
        print(f"🔧 [{group_name}] {[c['name'] for c in calls]} {time.perf_counter() - t0:.1f}s")
        return result
    except asyncio.TimeoutError:
        print(f"⏱️ [{group_name}] 超时（{timeout_seconds}s）: {[c['name'] for c in calls]}")
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
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None)
    if not tool_calls:
        return END

    groups_present = {TOOL_GROUP_MAP.get(c["name"], GROUP_SEARCH) for c in tool_calls}
    node_name = {GROUP_SEARCH: "tools_search", GROUP_REPORT: "tools_report"}
    return [Send(node_name[g], state) for g in groups_present]


def build_graph(checkpointer):
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
    return g.compile(checkpointer=checkpointer)


async def _make_async_checkpointer():
    try:
        raw = (os.getenv("CHAT_MEMORY_DB_PATH") or "").strip()
        if not raw:
            raise RuntimeError("未配置 CHAT_MEMORY_DB_PATH")

        db_path = os.path.expanduser(raw)
        # 新增：Git 不跟踪空目录，新服务器/新容器上目录可能不存在，aiosqlite 不会自动创建
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        
        conn = await aiosqlite.connect(os.path.expanduser(raw))
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        return saver
    except ImportError:
        print("⚠️ 未安装 langgraph-checkpoint-sqlite 或 aiosqlite，使用无记忆模式")
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
# 6. 初始化 / 关闭
# ============================================================
async def _load_mcp_tools_persistent(client: MultiServerMCPClient):
    """优先使用持久会话：整个服务只启动一个 MCP 子进程；失败则回退为每次调用新开会话"""
    global _exit_stack
    try:
        _exit_stack = AsyncExitStack()
        session = await _exit_stack.enter_async_context(client.session("news_mcp"))
        tools = await load_mcp_tools(session)
        print("✅ MCP 使用持久会话（单子进程）")
        return tools
    except Exception as e:
        print(f"⚠️ MCP 持久会话失败，回退为按次启动: {type(e).__name__}: {e}")
        if _exit_stack:
            try:
                await _exit_stack.aclose()
            except Exception:
                pass
            _exit_stack = None
        return await client.get_tools()


async def init_agent():
    global TOOLS, SEARCH_TOOLS, REPORT_TOOLS, agent_llm, app

    client = MultiServerMCPClient({
        "news_mcp": {
            "command": sys.executable,   # 改：用当前解释器，避免找错 python
            "args": [MCP_SCRIPT_PATH],
            "transport": "stdio",
            "env": os.environ.copy(),
        }
    })
    mcp_tools = await _load_mcp_tools_persistent(client)
    TOOLS = list(mcp_tools) + [request_daily_report]
    SEARCH_TOOLS, REPORT_TOOLS = _split_tools_by_group(TOOLS)
    print(f"✅ 加载工具: {[t.name for t in TOOLS]}")

    agent_llm = _base_llm.bind_tools(TOOLS)

    checkpointer = await _make_async_checkpointer()
    app = build_graph(checkpointer)
    return app


async def close_agent():
    """在 FastAPI shutdown / lifespan 结束时调用"""
    global _exit_stack
    if _exit_stack:
        await _exit_stack.aclose()
        _exit_stack = None


async def main():
    print("🚀 启动 Agent ...\n")
    app_instance = await init_agent()
    try:
        for q in ["给我强化学习相关新闻"]:
            print(f"\n=== 提问: {q} ===")
            t0 = time.perf_counter()
            try:
                r = await app_instance.ainvoke(
                    {"messages": [HumanMessage(content=q)]},
                    config={
                        "configurable": {"thread_id": f"test-{int(time.time())}"},
                        "recursion_limit": 10,
                    },
                )
            except Exception as e:
                print(f"❌ 执行失败: {type(e).__name__}: {e}")
                continue
            ans = r["messages"][-1].content
            print(f"回答({time.perf_counter() - t0:.1f}s):", ans[:400])
    finally:
        await close_agent()


if __name__ == "__main__":
    asyncio.run(main())