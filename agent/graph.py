import sys
import os
import json
import asyncio
import threading
import time
import traceback
from collections import Counter
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
from langgraph.errors import GraphRecursionError
from langchain_core.messages import (
    SystemMessage, HumanMessage, AIMessage, ToolMessage, trim_messages,
)
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from storage.db import get_connection, report_exists

try:
    from langgraph.types import Send
except ImportError:
    from langgraph.constants import Send  # type: ignore

from agent.llm_client import get_chat_model
from agent.prompts import build_agent_system_prompt

agent_llm = None   # 绑定工具的 LLM：负责决策
final_llm = None   # 不绑定工具的 LLM：触发停止条件后强制收尾，物理上无法再调工具

MCP_SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../mcp_server/news_mcp.py")
)

# ============================================================
# 0. 停止条件配置（所有阈值集中在这里，方便调参）
# ============================================================
MAX_TOOL_ROUNDS = 4        # 单次提问最多几轮「agent→工具」
MAX_EMPTY_SEARCHES = 2     # 搜索连续为空几次后不再搜（=首次 + 改写重搜 1 次）
MAX_TOOL_FAILS = 2         # 同一工具本轮失败（超时/报错）几次后熔断
TOOL_CALL_LIMITS = {       # 每个工具单次提问的调用次数上限
    "search_news": 3,
    "get_daily_report": 2,
    "request_daily_report": 1,
}
DEFAULT_TOOL_LIMIT = 3
REQUEST_TIMEOUT = 90       # 整个请求的总时限（秒），必须 > 单次 LLM + 工具耗时
RECURSION_LIMIT = 12       # 图步数硬上限；故意设得比业务上限大，只作最后保险
RETRY_BACKOFF = 0.5        # 工具重试前的等待（秒）

FAIL_STATUSES = {"timeout", "error"}  # 计入熔断计数的状态

# 工具返回给 LLM 的提示语：告诉模型「该怎么办」，避免它盲目重试
HINTS = {
    "timeout": "工具执行超时。本轮不要再调用该工具，请基于已有信息回答，并告知用户服务暂时繁忙。",
    "error": "工具执行出错：{detail}。不要用相同参数重试，请如实告知用户。",
    "circuit_open": "该工具本轮连续失败，已熔断。不要再调用，请基于已有信息回答。",
    "limit_reached": "该工具本轮调用次数已达上限，未执行。不要再调用，请基于已有结果回答。",
    "empty": "未检索到结果。最多可换一种关键词再搜一次；仍为空就如实告知用户没有相关新闻。",
}

# 触发强制收尾时追加到 system prompt 的指令
STOP_HINTS = {
    "max_rounds": "你已用完本次问题允许的工具调用轮数。不要再调用任何工具，基于已获得的结果回答；信息不足请明确说明。",
    "duplicate_call": "你刚才试图用相同参数重复调用工具，继续调用不会有新信息。不要再调用工具，基于已有结果回答。",
    "empty_exhausted": "多次检索均无结果。不要再调用工具，如实告诉用户没有找到相关内容，并建议换关键词或放宽时间范围。",
}
# final_llm 自己也失败时的固定兜底文案
FALLBACK_TEXT = {
    "max_rounds": "这个问题我查了几轮仍没能得到完整结果，请缩小范围或换个说法再试。",
    "duplicate_call": "我没能获得更多有效信息，请换个说法再试。",
    "empty_exhausted": "没有找到相关内容，可以试试换个关键词或放宽时间范围。",
}

EMPTY_MARKERS = ("没有找到", "未找到", "无相关", "暂无", "no results", "not found", "共 0")

# ============================================================
# 1. 通用小工具：从消息历史中「推导」本轮统计
#    只依赖 messages，不增加自定义 State 字段：
#    - 并行 Send 的两个工具节点不会写同一 key 而冲突
#    - 「本轮」以最后一条 HumanMessage 为界，换新问题自动清零
# ============================================================
def _text(content) -> str:
    return content if isinstance(content, str) else str(content)


def _try_json(text: str):
    t = text.strip()
    if not t.startswith("{"):
        return None
    try:
        return json.loads(t)
    except Exception:
        return None


def _sig(call: dict) -> str:
    """工具调用签名：工具名 + 规范化参数，用于判重"""
    return f'{call["name"]}:{json.dumps(call.get("args", {}), sort_keys=True, ensure_ascii=False)}'


def _current_turn(messages: list) -> list:
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return messages[i:]
    return messages


def _turn_stats(messages: list) -> dict:
    stats = {"rounds": 0, "sigs": set(), "calls": Counter(), "fails": Counter(), "empty": 0}
    for m in _current_turn(messages):
        if isinstance(m, AIMessage) and m.tool_calls:
            stats["rounds"] += 1
            for c in m.tool_calls:
                stats["sigs"].add(_sig(c))
                stats["calls"][c["name"]] += 1
        elif isinstance(m, ToolMessage):
            st = (m.additional_kwargs or {}).get("tool_status")
            if st in FAIL_STATUSES:
                stats["fails"][m.name] += 1
            elif st == "empty":
                stats["empty"] += 1
    return stats


def _is_search_call(call: dict) -> bool:
    return TOOL_GROUP_MAP.get(call["name"], GROUP_SEARCH) == GROUP_SEARCH


# ============================================================
# 2. 日报生成（后台线程直调 pipeline）
# ============================================================
BACKGROUND_TASKS: set = set()
_GEN_LOCKS: dict = {}
_GEN_LOCKS_GUARD = threading.Lock()


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


def _status_json(status: str, message: str) -> str:
    return json.dumps({"status": status, "message": message}, ensure_ascii=False)


async def trigger_report_generation(report_date: str, force: bool = False) -> str:
    """返回结构化 JSON：status=pending 表示「已受理/生成中」，agent 看到后直接收尾，不再轮询"""
    try:
        target = datetime.strptime(report_date, "%Y-%m-%d")
        report_date = target.strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return _status_json("error", "日报日期格式错误，请使用 YYYY-MM-DD。")

    with _GEN_LOCKS_GUARD:
        lock = _GEN_LOCKS.setdefault(report_date, threading.Lock())
    if not lock.acquire(blocking=False):
        return _status_json("pending", f"{report_date} 的日报正在生成中，请几分钟后再来查询。")

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
    return _status_json("pending", f"已启动 {report_date} 的日报生成任务，需要几分钟，请稍后再来查询。")


@tool
async def request_daily_report(report_date: str, force: bool = False) -> str:
    """当指定日期的日报不存在，且用户确实需要日报时调用。
    后台生成日报，立即返回，不等待生成完成。返回 pending 后本轮应直接结束，不要再查询。
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
# 重试改为在 _execute_with_retry 里自己做（RetryPolicy 只在节点抛异常时触发，
# 而超时/工具错误都被转成了 ToolMessage，RetryPolicy 永远不会生效）
GROUP_CONFIG = {
    GROUP_SEARCH: {"timeout_seconds": 30, "max_attempts": 2},
    GROUP_REPORT: {"timeout_seconds": 30, "max_attempts": 1},
}
TOOLS: list = []
SEARCH_TOOLS: list = []
REPORT_TOOLS: list = []
app = None
_exit_stack: AsyncExitStack | None = None


def _split_tools_by_group(all_tools):
    search_tools, report_tools = [], []
    for t in all_tools:
        group = TOOL_GROUP_MAP.get(t.name, GROUP_SEARCH)
        (search_tools if group == GROUP_SEARCH else report_tools).append(t)
    return search_tools, report_tools


# ============================================================
# 4. Agent 节点
# ============================================================
MAX_HISTORY_MSGS = 16
MAX_TOOL_CHARS = 3600


def _shrink(msgs):
    """截断历史里过长的工具返回"""
    out = []
    for m in msgs:
        if isinstance(m, ToolMessage):
            text = _text(m.content)
            if len(text) > MAX_TOOL_CHARS:
                m = ToolMessage(
                    content=text[:MAX_TOOL_CHARS] + "…(已截断)",
                    tool_call_id=m.tool_call_id,
                    name=m.name,
                    status=getattr(m, "status", "success"),
                    additional_kwargs=m.additional_kwargs,
                )
        out.append(m)
    return out


def _safe_trim(messages: list) -> list:
    """裁剪历史，并保证不会出现「孤立的 ToolMessage」"""
    msgs = trim_messages(
        messages,
        strategy="last",
        max_tokens=MAX_HISTORY_MSGS,
        token_counter=len,
        start_on="human",
        include_system=False,
    )
    if not msgs:
        msgs = _current_turn(messages)  # 兜底保留整个本轮，而不是只留最后一条
    while msgs and isinstance(msgs[0], ToolMessage):
        msgs = msgs[1:]
    return msgs


def _repair_history(msgs: list) -> list:
    """给「有 tool_calls 却没有对应 ToolMessage」的 AIMessage 补占位结果。
    场景：上次请求被超时/递归上限打断，checkpoint 里留下悬空的 tool_calls，
    不补的话同一 thread 的下一次提问会被模型 API 拒绝。只作用于送入 LLM 的副本。"""
    out = []
    for i, m in enumerate(msgs):
        out.append(m)
        if isinstance(m, AIMessage) and m.tool_calls:
            answered, j = set(), i + 1
            while j < len(msgs) and isinstance(msgs[j], ToolMessage):
                answered.add(msgs[j].tool_call_id)
                j += 1
            for c in m.tool_calls:
                if c["id"] not in answered:
                    out.append(ToolMessage(
                        content="[该工具调用未完成]", tool_call_id=c["id"], name=c["name"],
                    ))
    return out


def _pending_message(messages: list) -> str | None:
    """检查刚返回的工具结果里是否有 pending（日报已受理）。有就直接收尾，不再问 LLM"""
    tail = []
    for m in reversed(messages):
        if isinstance(m, ToolMessage):
            tail.append(m)
        else:
            break
    for m in tail:
        if (m.additional_kwargs or {}).get("tool_status") == "pending":
            data = _try_json(_text(m.content)) or {}
            return data.get("message") or "日报正在生成中，请几分钟后再来查询。"
    return None


def _check_limits(response: AIMessage, messages: list) -> str | None:
    """LLM 想继续调工具时，判断是否已触发停止条件。返回 stop_reason 或 None"""
    calls = response.tool_calls or []
    if not calls:
        return None
    s = _turn_stats(messages)  # 不含本次 response
    if s["rounds"] >= MAX_TOOL_ROUNDS:
        return "max_rounds"
    if any(_sig(c) in s["sigs"] for c in calls):
        return "duplicate_call"
    if s["empty"] >= MAX_EMPTY_SEARCHES and any(_is_search_call(c) for c in calls):
        return "empty_exhausted"
    return None


async def _finalize(system_text: str, msgs: list, reason: str) -> AIMessage:
    """强制收尾：用不绑定工具的 LLM 基于已有信息作答；它也失败就用固定文案"""
    try:
        resp = await final_llm.ainvoke(
            [SystemMessage(system_text + "\n\n" + STOP_HINTS[reason])] + _shrink(msgs)
        )
        if not isinstance(resp, AIMessage):
            resp = AIMessage(content=_text(resp.content))
    except Exception as e:
        print(f"⚠️ final_llm 失败，使用固定文案: {type(e).__name__}: {e}")
        resp = AIMessage(content=FALLBACK_TEXT[reason])
    resp.tool_calls = []
    resp.additional_kwargs = {**(resp.additional_kwargs or {}), "stop_reason": reason}
    return resp


async def agent_node(state: MessagesState):
    t0 = time.perf_counter()
    messages = state["messages"]

    # 停止条件①：日报已受理 -> 固定话术直接结束（切断 get/request 互相触发的死循环）
    pending = _pending_message(messages)
    if pending:
        print("🛑 stop_reason=async_pending")
        return {"messages": [AIMessage(
            content=pending, additional_kwargs={"stop_reason": "async_pending"},
        )]}

    today = datetime.now(timezone.utc).date().isoformat()
    system_text = build_agent_system_prompt(today)
    msgs = _repair_history(_safe_trim(messages))
    response = await agent_llm.ainvoke([SystemMessage(system_text)] + _shrink(msgs))

    # 停止条件②：LLM 还想调工具，但已超轮数 / 重复调用 / 搜索反复为空
    reason = _check_limits(response, messages)
    if reason:
        print(f"🛑 stop_reason={reason}，强制收尾")
        response = await _finalize(system_text, msgs, reason)

    print(
        f"🧠 agent LLM {time.perf_counter() - t0:.1f}s | "
        f"tool_calls={[c['name'] for c in (response.tool_calls or [])]} | 上下文={len(msgs)}条"
    )
    return {"messages": [response]}


# ============================================================
# 5. 工具节点：限额 / 熔断 / 超时重试 / 结果分类
# ============================================================
def _status_msg(call: dict, status: str, detail: str = "") -> ToolMessage:
    hint = HINTS[status].replace("{detail}", detail[:200])
    return ToolMessage(
        content=json.dumps({"status": status, "hint": hint}, ensure_ascii=False),
        tool_call_id=call["id"],
        name=call["name"],
        status="success" if status in ("ok", "empty", "pending") else "error",
        additional_kwargs={"tool_status": status},
    )


def _is_empty_result(text: str) -> bool:
    t = text.strip()
    if t in ("", "[]", "{}", "null", "None"):
        return True
    return len(t) < 200 and any(k in t for k in EMPTY_MARKERS)  # 只看短文本，避免误伤正文


def _postprocess(m: ToolMessage) -> ToolMessage:
    """给工具返回打上状态标签（ok / empty / pending / error），供统计和 LLM 判断"""
    text = _text(m.content)
    name = m.name or ""
    if getattr(m, "status", None) == "error":
        status, content = "error", json.dumps(
            {"status": "error", "hint": HINTS["error"].replace("{detail}", text[:200])},
            ensure_ascii=False,
        )
    else:
        parsed = _try_json(text)
        if isinstance(parsed, dict) and parsed.get("status") == "pending":
            status, content = "pending", text
        elif TOOL_GROUP_MAP.get(name, GROUP_SEARCH) == GROUP_SEARCH and _is_empty_result(text):
            status, content = "empty", json.dumps(
                {"status": "empty", "hint": HINTS["empty"]}, ensure_ascii=False
            )
        else:
            status, content = "ok", m.content
    return ToolMessage(
        content=content,
        tool_call_id=m.tool_call_id,
        name=m.name,
        status="error" if status == "error" else "success",
        additional_kwargs={"tool_status": status},
    )


async def _execute_with_retry(calls: list, group_tools: list, group_name: str) -> list:
    cfg = GROUP_CONFIG[group_name]
    node = ToolNode(group_tools, handle_tool_errors=True)
    attempts, status, detail = cfg["max_attempts"], "error", ""
    t0 = time.perf_counter()
    for attempt in range(1, attempts + 1):
        try:
            result = await asyncio.wait_for(
                node.ainvoke({"messages": [AIMessage(content="", tool_calls=calls)]}),
                timeout=cfg["timeout_seconds"],
            )
            print(f"🔧 [{group_name}] {[c['name'] for c in calls]} {time.perf_counter() - t0:.1f}s (第{attempt}次)")
            return [_postprocess(m) for m in result["messages"]]
        except (asyncio.TimeoutError, ConnectionError, OSError) as e:
            # 只有超时 / 连接类错误才值得重试
            status = "timeout" if isinstance(e, asyncio.TimeoutError) else "error"
            detail = f"{type(e).__name__}: {e}"
            print(f"⏱️ [{group_name}] 第{attempt}/{attempts}次失败({status}): {detail}")
            if attempt < attempts:
                await asyncio.sleep(RETRY_BACKOFF)
        except Exception as e:
            status, detail = "error", f"{type(e).__name__}: {e}"
            print(f"❌ [{group_name}] {detail}")
            break  # 非网络类异常，重试无意义
    return [_status_msg(c, status, detail) for c in calls]


async def _run_tool_group(state: MessagesState, group_tools: list, group_name: str):
    messages = state["messages"]
    last = messages[-1]
    calls = [c for c in (getattr(last, "tool_calls", None) or [])
             if TOOL_GROUP_MAP.get(c["name"], GROUP_SEARCH) == group_name]
    if not calls:
        return {"messages": []}

    prior = _turn_stats(messages[:-1])  # 不含当前这条 AIMessage
    used = Counter(prior["calls"])
    allowed, blocked = [], []
    for c in calls:
        name = c["name"]
        if prior["fails"].get(name, 0) >= MAX_TOOL_FAILS:          # 停止条件③：熔断
            blocked.append(_status_msg(c, "circuit_open"))
        elif used[name] >= TOOL_CALL_LIMITS.get(name, DEFAULT_TOOL_LIMIT):  # 停止条件④：单工具限额
            blocked.append(_status_msg(c, "limit_reached"))
        else:
            used[name] += 1
            allowed.append(c)

    results = await _execute_with_retry(allowed, group_tools, group_name) if allowed else []

    by_id = {m.tool_call_id: m for m in blocked + results}  # 按原 tool_calls 顺序返回
    return {"messages": [by_id[c["id"]] for c in calls if c["id"] in by_id]}


async def tools_search_node(state: MessagesState):
    return await _run_tool_group(state, SEARCH_TOOLS, GROUP_SEARCH)


async def tools_report_node(state: MessagesState):
    return await _run_tool_group(state, REPORT_TOOLS, GROUP_REPORT)


def route_after_agent(state: MessagesState):
    """没有 tool_calls 就结束（包含正常作答、强制收尾、日报 pending 三种情况）"""
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
    g.add_node("tools_search", tools_search_node)
    g.add_node("tools_report", tools_report_node)
    g.set_entry_point("agent")
    g.add_conditional_edges(
        "agent",
        route_after_agent,
        {"tools_search": "tools_search", "tools_report": "tools_report", END: END},
    )
    g.add_edge("tools_search", "agent")
    g.add_edge("tools_report", "agent")
    return g.compile(checkpointer=checkpointer)

_checkpointer_conn = None
async def _make_async_checkpointer():
    try:
        raw = (os.getenv("CHAT_MEMORY_DB_PATH") or "").strip()
        if not raw:
            raise RuntimeError("未配置 CHAT_MEMORY_DB_PATH")
        db_path = os.path.expanduser(raw)
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        conn = await aiosqlite.connect(db_path)
        _checkpointer_conn = conn
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
# 6. 统一入口：总时限 + 递归上限兜底（FastAPI 请调用它，不要直接 ainvoke）
# ============================================================
async def run_agent(question: str, thread_id: str) -> dict:
    """返回 {"answer": str, "stop_reason": str}，stop_reason 便于埋点统计各停止条件的触发率"""
    t0 = time.perf_counter()
    try:
        r = await asyncio.wait_for(
            app.ainvoke(
                {"messages": [HumanMessage(content=question)]},
                config={
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": RECURSION_LIMIT,
                },
            ),
            timeout=REQUEST_TIMEOUT,
        )
        last = r["messages"][-1]
        reason = (last.additional_kwargs or {}).get("stop_reason", "normal")
        result = {"answer": _text(last.content), "stop_reason": reason}
    except GraphRecursionError:
        result = {"answer": "这个问题我查了几轮仍没拿到可靠结果，请换个说法或缩小范围再试。",
                  "stop_reason": "recursion_limit"}
    except asyncio.TimeoutError:
        result = {"answer": "处理超时，请稍后重试。", "stop_reason": "request_timeout"}
    except Exception as e:
        traceback.print_exc()
        result = {"answer": "服务暂时出了点问题，请稍后重试。",
                  "stop_reason": f"error:{type(e).__name__}"}
    print(f"📊 stop_reason={result['stop_reason']} 耗时={time.perf_counter() - t0:.1f}s")
    return result


def run_analyst(title: str, content: str) -> dict:
    from agent.news_analyzer import analyze_news
    return analyze_news(title, content)


# ============================================================
# 7. 初始化 / 关闭
# ============================================================
async def _load_mcp_tools_persistent(client: MultiServerMCPClient):
    global _exit_stack
    try:
        _exit_stack = AsyncExitStack()
        session = await _exit_stack.enter_async_context(client.session("news_mcp"))
        tools = await load_mcp_tools(session)  #将 MCP Server 提供的工具转换成 LangChain 可以使用的工具对象
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
    global TOOLS, SEARCH_TOOLS, REPORT_TOOLS, agent_llm, final_llm, app
    client = MultiServerMCPClient({
        "news_mcp": {
            "command": sys.executable,
            "args": [MCP_SCRIPT_PATH],
            "transport": "stdio",
            "env": os.environ.copy(),
        }
    })
    mcp_tools = await _load_mcp_tools_persistent(client)
    TOOLS = list(mcp_tools) + [request_daily_report]
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
    # 不绑定工具的收尾模型；若你的 get_chat_model 要求必须传 tools，请传 tools=[]
    final_llm = get_chat_model(
        primary_env="LLM_MODEL",
        fallback_env="LLM_MODEL_FALLBACKS",
        timeout=40,
        streaming=True,
        enable_thinking=False,
    )

    checkpointer = await _make_async_checkpointer()
    app = build_graph(checkpointer)
    return app


async def close_agent():
    global _exit_stack, _checkpointer_conn
    if _exit_stack:
        await _exit_stack.aclose()
        _exit_stack = None
    if _checkpointer_conn:
        await _checkpointer_conn.close()
        _checkpointer_conn = None


async def main():
    print("🚀 启动 Agent ...\n")
    await init_agent()
    try:
        for q in ["给我强化学习相关新闻", "给我今天的日报"]:
            print(f"\n=== 提问: {q} ===")
            r = await run_agent(q, thread_id=f"test-{int(time.time())}")
            print(f"回答[{r['stop_reason']}]:", r["answer"][:400])
    finally:
        await close_agent()


if __name__ == "__main__":
    asyncio.run(main())