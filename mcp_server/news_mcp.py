# mcp_server/news_mcp.py
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp.server.fastmcp import FastMCP
from storage.db import get_connection, fetch_report_by_date
from retrieval.hybrid_search import hybrid_search, warmup

mcp = FastMCP("news-mcp")


@mcp.tool()
def search_news(query: str = None, category: str = None,
                limit: int = 5, min_importance: int = None) -> list[dict]:
    """新闻统一检索（关键词 + 语义混合检索，自动融合并重排）。
    适用于所有找新闻的场景：按主题/话题（如“强化学习相关新闻”）、
    按关键词、按分类、按重要度。同一问题只需调用一次。
    - query：自然语言问题或关键词；留空且指定 category 时按时间返回该分类新闻
    - category：可选，按 LLM 分类过滤
    - min_importance：可选，最低重要度
    返回标题、来源、链接、发布时间、摘要片段和相关度 score。"""
    return hybrid_search(query=query, category=category, limit=limit,
                         min_importance=min_importance)


@mcp.tool()
def get_daily_report(report_date: str) -> dict:
    """
    查询指定日期的日报。

    返回：
    - success：日报已存在
    - not_found：日报不存在
    """
    conn = get_connection()
    try:
        result = fetch_report_by_date(conn, report_date)

        if result:
            return {
                "status": "success",
                "report_date": report_date,
                "data": result,
                "message": f"{report_date} 的日报已生成。",
            }

        return {
            "status": "not_found",
            "report_date": report_date,
            "data": None,
            "message": (
                f"{report_date} 的日报尚未生成。"
                "如果用户需要这一天的日报，必须调用 request_daily_report 启动生成。"
            ),
        }

    except Exception as e:
        return {
            "status": "error",
            "report_date": report_date,
            "data": None,
            "message": f"查询日报失败：{type(e).__name__}: {e}",
        }

    finally:
        conn.close()


# request_daily_report：你给的文件里没有这个工具的代码，保持你原有实现不变即可。


if __name__ == "__main__":
    warmup()
    mcp.run(transport="stdio")