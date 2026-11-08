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
from agent.llm_client import get_chat_model
from agent.prompts import build_agent_system_prompt
agent_llm = None
MCP_SCRIPT_PATH = os.path.abspath(
          os.path.join(os.path.dirname(__file__), "../mcp_server/news_mcp.py")
)
# 改：明确工具分工、禁止绕路、限制输出长度

# ============================================================
# 2. 日报生成（后台线程直调 pipeline）
# ============================================================
BACKGROUND_TASKS: set = set()
_GEN_LOCKS: dict = {}
_GEN_LOCKS_GUARD = threading.Lock()
import traceback
def is_report_generating(report_date: str) -> bool:
          with _GEN_LOCKS_GUARD:
                    lock = _GEN_LOCKS.get(report_date)
                    return lock is not None and lock.locked()
def _run_daily_flow(report_date: str, force: bool):
          try:
                    from pipeline.flows.daily_news_flow import daily_flow
                    if not force:
                              conn = get_connection()
                              try:
                                        exists = report_exists(conn, report_date)
                              finally:
                                        conn.close()
                              if exists:
                                        print(f"🔍 {report_date} 日报已存在，跳过生成")
                                        return
                    target = datetime.strptime(report_date, "%Y-%m-%d").date()
                    print(f"🚀 后台启动 daily_flow: {target} (force={force})")
                    daily_flow(run_date=target)
  # 检查流程结束后，数据库中是否真的存在日报
                    conn = get_connection()
                    try:
                              exists = report_exists(conn, report_date)
                    finally:
                              conn.close()
                    if exists:
                              print(f"✅ 日报生成完成: {report_date}")
                    else:
                              print(f"⚠️ 流程已结束，但数据库中没有 {report_date} 的日报")
          except Exception as e:
                    traceback.print_exc()
                    print(f"❌ 日报生成失败: {report_date}: {type(e).__name__}: {e}")
async def trigger_report_generation(
          report_date: str,
          force: bool = False,
) -> str:
          try:
                    target = datetime.strptime(report_date, "%Y-%m-%d")
                    report_date = target.strftime("%Y-%m-%d")
          except (TypeError, ValueError):
                    return "日报日期格式错误，请使用 YYYY-MM-DD。"
          with _GEN_LOCKS_GUARD:
                    lock = _GEN_LOCKS.setdefault(report_date, threading.Lock())
          if not lock.acquire(blocking=False):
                    return f"{report_date} 的日报正在生成中，请稍后查询。"
          def _guarded():
                    try:
                              _run_daily_flow(report_date, force)
                    finally:
                              lock.release()
          try:
                    task = asyncio.create_task(asyncio.to_thread(_guarded))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
          except Exception:
                    lock.release()
                    raise
          return (
                    f"已启动 {report_date} 的日报生成任务。"
                    "生成需要几分钟，请稍后查询。"
          )
@tool
async def request_daily_report(
          report_date: str,
          force: bool = False,
) -> str:
          """当指定日期的日报不存在，且用户确实需要日报时调用。
          后台生成日报，立即返回，不等待生成完成。
          用户明确要求重新生成时，force 设置为 true。"""
          return await trigger_report_generation(report_date, force)
# ============================================================
# 3. 工具分组
# ============================================================
GROUP_SEARCH = "search"
GROUP_REPORT = "report"
TOOL_GROUP_MAP = {
          "search_news": GROUP_SEARCH,
          "get_daily_report": GROUP_REPORT,
          "request_daily_report": GROUP_REPORT,
}
GROUP_CONFIG = {
          GROUP_SEARCH: {"timeout_seconds": 30, "retry": RetryPolicy(max_attempts=2)},
          GROUP_REPORT: {"timeout_seconds": 30, "retry": RetryPolicy(max_attempts=1)},
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
MAX_HISTORY_MSGS = 16  # 送入 LLM 的最近消息条数
MAX_TOOL_CHARS = 3600  # 历史里单条工具结果的最大字符数
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
          system = SystemMessage(build_agent_system_prompt(today))
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
          response = await agent_llm.ainvoke([system] + _shrink(msgs))  #3 模型决策
          print(
                    f"🧠 agent LLM {time.perf_counter() - t0:.1f}s | "
                    f"tool_calls={[c['name'] for c in (response.tool_calls or [])]} | 上下文={len(msgs)}条"
          )
          return {"messages": [response]}

#5 ToolNode 执行
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
#4 LangGraph 路由
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
          client = MultiServerMCPClient({   # 1.MCP 工具加载
                    "news_mcp": {
                              "command": sys.executable,  # 改：用当前解释器，避免找错 python
                              "args": [MCP_SCRIPT_PATH],
                              "transport": "stdio",
                              "env": os.environ.copy(),
                    }
          })
          mcp_tools = await _load_mcp_tools_persistent(client)
          TOOLS = list(mcp_tools) + [request_daily_report]   #2.工具注册
          SEARCH_TOOLS, REPORT_TOOLS = _split_tools_by_group(TOOLS)
          print(f"✅ 加载工具: {[t.name for t in TOOLS]}")
          agent_llm = get_chat_model(
          primary_env="LLM_MODEL",
          fallback_env="LLM_MODEL_FALLBACKS",
          timeout=40,
          streaming=True,
          enable_thinking=False,
          tools=TOOLS,
)
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
