# mcp_server/news_mcp.py
import os
import sys
import time

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp.server.fastmcp import FastMCP
from storage.db import get_connection, query_news, fetch_report_by_date
from storage.vectorstore import vectorstore

mcp = FastMCP("news-mcp")

SNIPPET_CHARS = 200
MAX_TOP_K = 8
KEEP_FULL_KEYS = {"url", "link", "source", "title", "category", "published_at", "date"}


def _snippet(text, n: int = SNIPPET_CHARS) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "…"


def _slim_row(row) -> dict:
    """不依赖具体列名：除白名单字段外，所有长字符串一律截断"""
    r = dict(row)
    for k, v in r.items():
        if isinstance(v, str) and k not in KEEP_FULL_KEYS and len(v) > SNIPPET_CHARS:
            r[k] = _snippet(v)
    return r


@mcp.tool()
def search_news(keyword: str = None, category: str = None, limit: int = 8) -> list[dict]:
    """仅用于用户明确指定分类或精确关键词匹配的查询（返回标题和摘要）。
    按主题/话题找新闻请改用 search_news_semantic。"""
    limit = max(1, min(limit, MAX_TOP_K))
    conn = get_connection()
    try:
        rows = query_news(conn, keyword=keyword, category=category, limit=limit)
    finally:
        conn.close()
    return [_slim_row(r) for r in rows]


@mcp.tool()
def search_news_semantic(query: str, top_k: int = 5) -> list[dict]:
    """按主题/话题/问题做语义检索，返回最相关的新闻（如“强化学习相关新闻”）。
    同一问题只需调用一次。"""
    top_k = max(1, min(top_k, MAX_TOP_K))
    t0 = time.perf_counter()

    docs = vectorstore.similarity_search(query, k=top_k)
    print(f"🔎 semantic '{query}' -> {len(docs)} 条, {time.perf_counter() - t0:.2f}s", file=sys.stderr)

    results = []
    for d in docs:
        meta = d.metadata or {}
        results.append({
            "content": _snippet(d.page_content),
            "news_id": meta.get("news_id") or meta.get("id"),
            "title": meta.get("title", "未知标题"),
            "source": meta.get("source", "未知来源"),
            "url": meta.get("url") or meta.get("link"),
            "published": meta.get("published_at") or meta.get("date"),
        })
    if not results:
        print("⚠️ 向量库检索无结果，请检查向量库是否有数据", file=sys.stderr)
    return results


@mcp.tool()
def get_daily_report(report_date: str) -> dict:
    """获取指定日期(YYYY-MM-DD)的每日新闻简报"""
    conn = get_connection()
    try:
        result = fetch_report_by_date(conn, report_date)
        return result if result else {"content": None}
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        t0 = time.perf_counter()
        vectorstore.similarity_search("warm up", k=1)
        print(f"✅ 向量库预热完成 {time.perf_counter() - t0:.1f}s", file=sys.stderr)
    except Exception as e:
        print(f"⚠️ 预热失败: {e}", file=sys.stderr)

    mcp.run(transport="stdio")