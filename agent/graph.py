# agent/graph.py



import sys
import os
import json
import asyncio
from datetime import date, timedelta
from dotenv import load_dotenv

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv()

from langgraph.graph import StateGraph, END
from typing import TypedDict, Literal, Optional
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from storage.db import fetch_report_by_date, get_connection

# 后台生成任务集合，防止被 GC 回收
BACKGROUND_TASKS: set[asyncio.Task] = set()

# ============================================================
# 1. LLM 配置
# ============================================================
router_llm = ChatOpenAI(
    model=os.getenv("LLM_ROUTER", "glm-4.5-air"),
    openai_api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL"),
    temperature=0.0,
)

generator_llm = ChatOpenAI(
    model=os.getenv("LLM_GENERATOR", "deepseek-r1"),
    openai_api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL"),
    temperature=0.3,
)

# MCP Server 脚本的绝对路径
MCP_SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../mcp_server/news_mcp.py")
)


# ============================================================
# 2. 工具函数
# ============================================================
def parse_mcp_result(result) -> list | dict:
    if result is None:
        return []

    # 🌟 修复：[{"type":"text","text":"..."}, ...] 结构 —— 逐条解析
    if (
        isinstance(result, list)
        and result
        and isinstance(result[0], dict)
        and "type" in result[0]
        and "text" in result[0]
    ):
        items = []
        for entry in result:
            if not isinstance(entry, dict):
                continue
            text = entry.get("text", "")
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            # 如果解析出来是 list，展开；如果是 dict，追加
            if isinstance(parsed, list):
                items.extend(parsed)
            else:
                items.append(parsed)
        return items

    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return []

    return result


async def astream_invoke(llm, prompt: str) -> str:
    """异步流式拼接 LLM 输出"""
    full_content = ""
    async for chunk in llm.astream(prompt):
        if chunk.content:
            full_content += chunk.content
    return full_content


def load_local_daily_report(report_date: str) -> dict | None:
    """Read the report from the same database used by the API."""
    conn = get_connection()
    try:
        row = fetch_report_by_date(conn, report_date)
        if not row:
            return None
        report = json.loads(row["report_json"])
        return report if isinstance(report, dict) else None
    except (TypeError, json.JSONDecodeError):
        return None
    finally:
        conn.close()


def format_daily_report(report_date: str, report: dict) -> str:
    overview = report.get("overview") or "暂无日报概览。"
    events = report.get("events") or []
    lines = [f"以下是 {report_date} 的新闻简报：", "", overview, "", "重点事件："]
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict):
            continue
        title = event.get("title") or "未命名事件"
        detail = event.get("summary") or event.get("why_it_matters") or "暂无补充说明。"
        lines.append(f"{index}. {title}\n   {detail}")
    return "\n".join(lines)


# ============================================================
# 3. 共享状态定义
# ============================================================
class AgentState(TypedDict):
    question: str
    route: Optional[Literal["knowledge", "summarizer", "generator"]]
    docs: list
    sources: list
    report_date: Optional[str]
    answer: str


# 全局 TOOL_MAP，将在 init_agent 中动态赋值
TOOL_MAP = {}

# 后台生成任务集合，防止被 GC 回收
BACKGROUND_TASKS: set[asyncio.Task] = set()

# 后台任务直接调 flow，不经过 MCP
async def _trigger_report_generation(report_date: str):
    def _run():
        from datetime import datetime
        from pipeline.flows.daily_news_flow import daily_flow
        target = datetime.strptime(report_date, "%Y-%m-%d").date()
        daily_flow(run_date=target)   # 和你 __main__ 里的调用方式一致

    try:
        await asyncio.to_thread(_run)   # 或者保持 create_task 包裹
        print(f"✅ 日报生成完成: {report_date}")
    except Exception as e:
        print(f"❌ 日报生成失败: {type(e).__name__}: {e}")
# ============================================================
# 4. Supervisor（路由分类 + 日期解析）
# ============================================================
async def supervisor(state: AgentState):
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    prompt = f"""你是一个路由分类器，判断用户问题应该交给哪个模块处理。
只输出严格的 JSON，不要有任何 Markdown 格式（如 ```json），不要有其他文字：
{{"route": "knowledge" 或 "summarizer", "report_date": "YYYY-MM-DD 或 null"}}

今天的日期是：{today}
昨天的日期是：{yesterday}

规则：
- 如果用户是在问某个具体主题/事件的资讯（例如"最近大模型发布有什么进展"），route="knowledge"
- 如果用户是要简报/日报/总结（例如"今天有什么重要新闻""帮我总结一下"），route="summarizer"
- 如果用户提到"今天"，report_date 必须是 {today}
- 如果用户提到"昨天"，report_date 必须是 {yesterday}
- 如果用户提到其他具体日期，解析成 YYYY-MM-DD
- 如果用户没提到任何日期，report_date 必须是 null
- 如果用户明确要求"生成/跑/构建"某天日报（例如"帮我生成昨天的日报"），route="generator"

用户问题：{state['question']}
"""
    resp_content = await astream_invoke(router_llm, prompt)
    content = (
        resp_content.strip()
        .removeprefix("```json")
        .removesuffix("```")
        .strip()
    )
    try:
        parsed = json.loads(content)
    except Exception:
        parsed = {"route": "knowledge", "report_date": None}

    route = parsed.get("route", "knowledge")
    parsed_date = parsed.get("report_date")

    # 🌟 修复 2：代码兜底 —— 用户明确说"今天/昨天"时，以代码为准
    question = state["question"]
    if any(kw in question for kw in ("今天", "今日")):
        parsed_date = today
    elif any(kw in question for kw in ("昨天", "昨日")):
        parsed_date = yesterday

    print(
        f"🔍 supervisor: route={route}, report_date={parsed_date!r} "
        f"(LLM 原始: {parsed.get('report_date')!r})"
    )

    return {"route": route, "report_date": parsed_date}


def route_decision(state: AgentState) -> Literal["knowledge", "summarizer"]:
    return state["route"]


# ============================================================
# 5. Knowledge Agent
# ============================================================
async def kb_retrieve(state: AgentState):
    if "search_news_semantic" not in TOOL_MAP:
        print("❌ 警告: MCP 中未找到 search_news_semantic 工具")
        return {"docs": []}

    search_tool = TOOL_MAP["search_news_semantic"]
    try:
        result = await search_tool.ainvoke(
            {"query": state["question"], "top_k": 5}
        )

        # 🌟 调试：看原始返回
        print(f"🔍 kb_retrieve raw result: {result!r}")

        docs_data = parse_mcp_result(result)

        print(f"🔍 kb_retrieve parsed: {docs_data!r}")

        # 确保 docs_data 是 list[dict]
        if isinstance(docs_data, dict):
            docs_data = [docs_data]
        if not isinstance(docs_data, list):
            docs_data = []

        return {"docs": docs_data}
    except Exception as e:
        print(f"❌ MCP 检索失败: {e}")
        return {"docs": []}


async def kb_generate(state: AgentState):
    if not state["docs"]:
        return {"answer": "抱歉，没有检索到相关资讯，无法回答这个问题。", "sources": []}

    context_blocks = []
    sources = []
    for i, d in enumerate(state["docs"], 1):
        if isinstance(d, dict):
            title = d.get("title") or ""
            content = (
                d.get("content")
                or d.get("summary")
                or d.get("page_content")
                or ""
            )
            news_id = d.get("news_id")
            source = d.get("source")
        else:
            meta = getattr(d, "metadata", {}) or {}
            title = meta.get("title") or ""
            content = getattr(d, "page_content", "") or ""
            news_id = meta.get("news_id")
            source = meta.get("source")

        context_blocks.append(f"[{i}] 标题:{title}\n{content}")
        sources.append({"news_id": news_id, "title": title, "source": source})

    context = "\n\n".join(context_blocks)
    prompt = (
        f"根据以下资讯回答问题，回答中用[序号]标注引用了哪条资讯。\n\n"
        f"资讯:\n{context}\n\n问题: {state['question']}"
    )
    resp_content = await astream_invoke(generator_llm, prompt)
    return {"answer": resp_content, "sources": sources}


# ============================================================
# 6. Summarizer Agent
# ============================================================
async def summarizer(state: AgentState):
    report_date = state.get("report_date")
    print(f"🔍 summarizer report_date = {report_date!r}")

    if not report_date:
        today = date.today().isoformat()
        return {
            "answer": (
                f"抱歉，生成简报需要指定具体日期。"
                f"例如：'帮我总结一下 {today} 的新闻'，"
                f"或说 '帮我生成 {today} 的日报'。"
            ),
            "sources": [],
        }

    local_report = await asyncio.to_thread(load_local_daily_report, report_date)
    if local_report:
        return {
            "answer": format_daily_report(report_date, local_report),
            "sources": [],
        }

    if "get_daily_report" not in TOOL_MAP:
        return {"answer": "系统暂不支持日报查询功能。", "sources": []}

    result = await TOOL_MAP["get_daily_report"].ainvoke({"report_date": report_date})
    report_data = parse_mcp_result(result)

    # ✅ 情况一：有日报，直接输出
    if isinstance(report_data, dict) and report_data.get("content"):
        content = report_data["content"]
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                pass
        if isinstance(content, dict):
            content = format_daily_report(report_date, content)
        return {
            "answer": content if isinstance(content, str) else str(content),
            "sources": [],
        }

    # 🌟 情况二：无日报 → 后台触发 pipeline，立即回复用户
    task = asyncio.create_task(_trigger_report_generation(report_date))
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(BACKGROUND_TASKS.discard)

    return {
        "answer": (
            f"数据库中暂无 {report_date} 的日报。📋 已为您启动后台生成任务"
            f"（包括新闻抓取、去重、分析、向量化与汇总，预计需要几分钟）。\n\n"
            f"请稍后重新发送「帮我总结 {report_date} 的新闻」即可获取。"
        ),
        "sources": [],
    }


# ============================================================
# 增加节点
# ============================================================
async def report_generator(state: AgentState):
    """用户主动要求生成指定日期的日报"""
    report_date = state.get("report_date") or date.today().isoformat()

    task = asyncio.create_task(_trigger_report_generation(report_date))
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(BACKGROUND_TASKS.discard)

    return {
        "answer": (
            f"已开始为 {report_date} 生成日报 🚀（流程：抓取 → 去重 → 分析 → 向量化 → 汇总，"
            f"预计需要几分钟）。完成后您可以直接问我「{report_date} 的新闻简报」。"
        ),
        "sources": [],
    }


# ============================================================
# 7. 构建图
# ============================================================
def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("kb_retrieve", kb_retrieve)
    graph.add_node("kb_generate", kb_generate)
    graph.add_node("summarizer", summarizer)
    graph.add_node("generator", report_generator)

    graph.set_entry_point("supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_decision,
        {"knowledge": "kb_retrieve", "summarizer": "summarizer","generator": "generator"},
    )
    graph.add_edge("kb_retrieve", "kb_generate")
    graph.add_edge("kb_generate", END)
    graph.add_edge("summarizer", END)
    graph.add_edge("generator",END)

    return graph.compile()


# ============================================================
# 8. Analyst（独立函数）
# ============================================================
def run_analyst(title: str, content: str) -> dict:
    from agent.news_analyzer import analyze_news
    return analyze_news(title, content)


# ============================================================
# 9. 一次性初始化（供 FastAPI lifespan 调用）
# ============================================================
async def init_agent():
    global TOOL_MAP, app

    client = MultiServerMCPClient({
        "news_mcp": {
            "command": "python",
            "args": [MCP_SCRIPT_PATH],
            "transport": "stdio",
            "env": os.environ.copy(),
        }
    })
    mcp_tools = await client.get_tools()
    TOOL_MAP = {tool.name: tool for tool in mcp_tools}
    print(f"✅ 成功加载 MCP 工具: {list(TOOL_MAP.keys())}")

    app = build_graph()
    return app


# ============================================================
# 10. 本地测试入口
# ============================================================
async def main():
    global TOOL_MAP, app

    print("🚀 正在启动 LangGraph Agent (MCP 模式)...\n")

    client = MultiServerMCPClient({
        "news_mcp": {
            "command": "python",
            "args": [MCP_SCRIPT_PATH],
            "transport": "stdio",
            "env": os.environ.copy(),
        }
    })

    mcp_tools = await client.get_tools()
    TOOL_MAP = {tool.name: tool for tool in mcp_tools}
    print(f"✅ 成功加载 MCP 工具: {list(TOOL_MAP.keys())}\n")

    app = build_graph()

    # # 测试 Knowledge 路由
    # print("=== 测试 Knowledge 路由 ===")
    # r1 = await app.ainvoke({"question": "最近有哪些大模型发布的新闻？"})
    # print("回答:", r1["answer"])
    # print("来源:", r1.get("sources"))

    # print("\n" + "=" * 50 + "\n")

    # # 测试 Summarizer 路由
    # print("=== 测试 Summarizer 路由 ===")
    # r2 = await app.ainvoke({"question": "帮我总结一下昨天的重要新闻"})
    # print("回答:", r2["answer"])
    # print("来源:", r2.get("sources"))

    # 测试 Generator 路由
    r = await app.ainvoke({"question": "帮我生成 2026-09-01 的日报"})
    print(r["answer"]) 

if __name__ == "__main__":
    asyncio.run(main())