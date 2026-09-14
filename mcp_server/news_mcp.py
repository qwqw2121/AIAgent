# mcp_server/news_mcp.py
from mcp.server.fastmcp import FastMCP
from storage.db import get_connection, query_news, fetch_by_status

mcp = FastMCP("news-mcp")

@mcp.tool()
def search_news(keyword: str = None, category: str = None, min_importance: int = None, limit: int = 20) -> list[dict]:
    """检索已分析的新闻，供 Agent 做问答/简报使用"""
    conn = get_connection()
    try:
        return query_news(conn, category=category, keyword=keyword, min_importance=min_importance, limit=limit)
    finally:
        conn.close()

@mcp.tool()
def get_pending_stats() -> dict:
    conn = get_connection()
    try:
        rows = fetch_by_status(conn, status=("deduped",))
        return {"pending_analysis": len(rows)}
    finally:
        conn.close()

if __name__ == "__main__":
    mcp.run(transport="stdio")  # 或 "sse" 给远程调用