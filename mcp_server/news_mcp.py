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
@mcp.tool()
def search_news(
    query: str = None,
    category: str = None,
    limit: int = 5,
    min_importance: int = None,
) -> list[dict]:
    """
    新闻统一检索（关键词 + 向量混合检索）。

    支持：
    - 按主题、关键词检索新闻
    - 按时间范围检索新闻
    - 按分类和重要性筛选
    - 自动扩大时间范围，避免近期结果不足时直接返回空结果

    时间检索规则：
    - 优先返回用户指定时间范围内的新闻。
    - 指定范围内不足 limit 条时，自动扩大至 30 天、90 天。
    - 返回结果包含 time_scope：
      requested：用户指定时间范围内
      expanded_30d：30 天扩展结果
      expanded_90d：90 天扩展结果

    注意：
    不得将扩展范围的旧新闻描述为用户指定时间范围内的新闻。
    """
    return hybrid_search(
        query=query,
        category=category,
        limit=limit,
        min_importance=min_importance,
    )


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