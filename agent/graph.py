# agent/graph.py
# Supervisor + Knowledge Agent + Summarizer Agent + Analyst(独立函数,不接入对话路由)
import sys
import os
# 添加项目根目录到 Python 路径

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import json
from dotenv import load_dotenv
load_dotenv()

from langgraph.graph import StateGraph, END
from typing import TypedDict, Literal, Optional
from storage.vectorstore import get_retriever
from storage.db import get_connection, query_news
from langchain_openai import ChatOpenAI

# ============================================================
# LLM 配置（保持原样）
# ============================================================
API_KEY = os.getenv("LLM_API_KEY")
BASE_URL = os.getenv("LLM_BASE_URL")
MODEL_NAME = os.getenv("LLM_MODEL")

if not API_KEY or not BASE_URL or not MODEL_NAME:
    raise ValueError("❌ 错误：请在 .env 文件中配置 LLM_API_KEY, LLM_BASE_URL, LLM_MODEL")

llm = ChatOpenAI(
    model=MODEL_NAME,
    openai_api_key=API_KEY,
    base_url=BASE_URL,
)

retriever = get_retriever()


# ============================================================
# 共享状态
# ============================================================
class AgentState(TypedDict):
    question: str
    route: Optional[Literal["knowledge", "summarizer"]]
    docs: list
    sources: list
    report_date: Optional[str]      # 用户问的是哪天的简报，Supervisor解析出来
    answer: str


# ============================================================
# Supervisor：判断问题该交给 Knowledge 还是 Summarizer
# ============================================================
def supervisor(state: AgentState):
    prompt = f"""你是一个路由分类器，判断用户问题应该交给哪个模块处理。
只输出JSON，不要有其他文字：
{{"route": "knowledge" 或 "summarizer", "report_date": "YYYY-MM-DD 或 null"}}

规则：
- 如果用户是在问某个具体主题/事件的资讯（比如"最近大模型发布有什么进展"），route="knowledge"
- 如果用户是要简报/日报/总结（比如"今天有什么重要新闻""帮我总结一下"），route="summarizer"
- 如果用户提到了具体日期或"今天""昨天"，解析成 report_date；没提到就是 null

用户问题：{state['question']}
"""
    resp = llm.invoke(prompt)
    try:
        parsed = json.loads(resp.content)
    except Exception:
        parsed = {"route": "knowledge", "report_date": None}
    return {"route": parsed.get("route", "knowledge"), "report_date": parsed.get("report_date")}


def route_decision(state: AgentState) -> Literal["knowledge", "summarizer"]:
    return state["route"]


# ============================================================
# Knowledge Agent：检索 + 生成，带引用来源
# ============================================================
def kb_retrieve(state: AgentState):
    docs = retriever.invoke(state["question"])
    return {"docs": docs}


def kb_generate(state: AgentState):
    if not state["docs"]:
        return {"answer": "抱歉，没有检索到相关资讯，无法回答这个问题。", "sources": []}

    context_blocks = []
    sources = []
    for i, d in enumerate(state["docs"], 1):
        meta = d.metadata or {}
        context_blocks.append(f"[{i}] 标题:{meta.get('title','')}\n{d.page_content}")
        sources.append({
            "news_id": meta.get("news_id"),
            "title": meta.get("title"),
            "source": meta.get("source"),
        })
    context = "\n\n".join(context_blocks)
    prompt = f"根据以下资讯回答问题，回答中用[序号]标注引用了哪条资讯。\n\n资讯:\n{context}\n\n问题: {state['question']}"
    resp = llm.invoke(prompt)
    return {"answer": resp.content, "sources": sources}


# ============================================================
# Summarizer Agent：优先取已生成简报，没有就现场生成
# ============================================================
def get_daily_report(report_date: str) -> Optional[dict]:
    """对应 mcp-search 里 get_daily_report tool 的逻辑，先复用为本地函数"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM daily_reports WHERE report_date = %s", (report_date,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def summarizer(state: AgentState):
    # 1. 有明确日期，且当天简报已经由 Prefect report_task 生成过 -> 直接取，不重新生成
    if state.get("report_date"):
        existing = get_daily_report(state["report_date"])
        if existing:
            return {"answer": existing["content"], "sources": []}

    # 2. 没有现成简报（比如用户问的是任意范围，如"这周关于Agent的新闻"）-> 现场生成
    conn = get_connection()
    try:
        news_list = query_news(conn, min_importance=7, limit=15)
    finally:
        conn.close()

    if not news_list:
        return {"answer": "暂无可用于生成简报的资讯。", "sources": []}

    context = "\n".join(f"- {n['title']}（{n.get('llm_category','')}）：{n.get('summary','')}" for n in news_list)
    prompt = f"""请根据以下资讯生成一份简报，包含分类小标题和每条要点，语言简洁。

资讯列表:
{context}

用户请求: {state['question']}
"""
    resp = llm.invoke(prompt)
    sources = [{"news_id": n["id"], "title": n["title"], "source": n.get("source")} for n in news_list]
    return {"answer": resp.content, "sources": sources}


# ============================================================
# 构建主对话图：Supervisor -> (Knowledge | Summarizer) -> END
# ============================================================
graph = StateGraph(AgentState)
graph.add_node("supervisor", supervisor)
graph.add_node("kb_retrieve", kb_retrieve)
graph.add_node("kb_generate", kb_generate)
graph.add_node("summarizer", summarizer)

graph.set_entry_point("supervisor")
graph.add_conditional_edges(
    "supervisor",
    route_decision,
    {"knowledge": "kb_retrieve", "summarizer": "summarizer"},
)
graph.add_edge("kb_retrieve", "kb_generate")
graph.add_edge("kb_generate", END)
graph.add_edge("summarizer", END)

app = graph.compile()


# ============================================================
# Analyst：独立函数，不接入对话路由，由 Prefect pipeline 直接调用
# 复用 agent/news_analyzer.py 里现成的 analyze_news，这里不重复实现
# ============================================================
def run_analyst(title: str, content: str) -> dict:
    """
    说明：这不是 LangGraph 节点，是给 Prefect analysis_task 调用的既有能力。
    放在这里仅为了在同一个文件里体现"四个智能体"的完整架构，
    实际调用方仍是 pipeline/tasks/analysis_task.py，不经过 Supervisor。
    """
    from agent.news_analyzer import analyze_news
    return analyze_news(title, content)


if __name__ == "__main__":
    # 测试 Knowledge 路由
    # r1 = app.invoke({"question": "最近有哪些大模型发布的新闻？"})
    # print("=== Knowledge ===")
    # print(r1["answer"])
    # print(r1.get("sources"))

    # 测试 Summarizer 路由
    
    r2 = app.invoke({"question": "帮我总结一下今天的重要新闻"})
    print("\n=== Summarizer ===")
    print(r2["answer"])