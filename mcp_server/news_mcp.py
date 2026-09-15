# mcp_server/news_mcp.py
import os
import sys
import json
import datetime
# 🌟 关键修复：将项目根目录加入 sys.path，确保子进程能找到 storage 模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp.server.fastmcp import FastMCP
from storage.db import get_connection, query_news, fetch_report_by_date
from storage.vectorstore import get_retriever  # 引入向量库

mcp = FastMCP("news-mcp")

# 1. 原有的精确查询
@mcp.tool()
def search_news(keyword: str = None, category: str = None, limit: int = 20) -> list[dict]:
    """基于关键词或分类的精确/模糊查询"""
    conn = get_connection()
    try:
        return query_news(conn, keyword=keyword, category=category, limit=limit)
    finally:
        conn.close()

# 2. 语义检索 (增强防御性和调试信息)
@mcp.tool()
def search_news_semantic(query: str, top_k: int = 5) -> list[dict]:
    """基于用户问题的语义向量检索，返回最相关的新闻片段"""
    retriever = get_retriever()
    docs = retriever.invoke(query)
    
    results = []
    for d in docs:
        meta = d.metadata
        results.append({
            "content": d.page_content, 
            # 🌟 修复：兼容不同的 key 命名 (news_id 或 id)
            "news_id": meta.get("news_id") or meta.get("id"),
            "title": meta.get("title", "未知标题"),
            "source": meta.get("source", "未知来源"),
        })
    
    # 如果查不到，打印警告，方便你排查向量库问题
    if not results:
        print(f"⚠️ 向量库检索无结果，请检查: 1. 向量库是否有数据 2. embed是否成功")
        
    return results

# 3. 获取每日简报 (修复列名错误)
@mcp.tool()
def get_daily_report(report_date: str) -> dict:
    """获取指定日期(YYYY-MM-DD)的每日新闻简报"""
    conn = get_connection()
    try:
        # 🌟 修复：列名从 content 改为 report_json
        cur = conn.execute("SELECT report_json FROM daily_reports WHERE report_date = ?", (report_date,))
        row = cur.fetchone()
        # 🌟 修复：使用 row[0] 获取第一列的值 (tuple 索引)
        return {"content": row[0]} if row else {"content": None}
    finally:
        conn.close()

# ---------- 新增：生成指定日期日报 ----------
@mcp.tool()
def generate_daily_report(report_date: str, force: bool = False) -> dict:
    """
    生成指定日期的新闻日报。
    - report_date: YYYY-MM-DD
    - force: 如果该日期已有日报，是否强制重新生成。默认 False（已存在则直接返回）。

    返回: {"report_date": ..., "overview": ..., "content": ..., "generated": True/False}
    """
    # 1. 校验日期
    try:
        datetime.strptime(report_date, "%Y-%m-%d")
    except ValueError:
        return {"error": f"日期格式错误: {report_date}，应为 YYYY-MM-DD"}

    # 2. 如果已有且不强制重生成，直接返回
    if not force:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT report_date, overview, report_json FROM daily_reports WHERE report_date = ?",
                (report_date,),
            ).fetchone()
            if row:
                return {
                    "report_date": row["report_date"],
                    "overview": row["overview"],
                    "content": row["report_json"],
                    "generated": False,   # 表示"复用已有"
                }
        finally:
            conn.close()

    # 3. 触发 report_task 生成
    #    注意：report_task 是 Prefect task，这里直接调它的底层函数，
    #    不要 .fn() 之外的方式，避免依赖 Prefect runtime。
    try:
        from pipeline.tasks.report_task import report_task
        from pipeline.state import PipelineState
        from datetime import datetime as _dt

        run_date = _dt.strptime(report_date, "%Y-%m-%d").date()

        # 构造一个最小 state，让 report_task 能跑
        # 具体字段名按你 report_task 的实际入参调整
        state = PipelineState(run_date=run_date)

        # 如果 report_task 是 @task 装饰的，用 .fn() 拿到底层函数
        report_fn = getattr(report_task, "fn", report_task)
        new_state = report_fn(state)

        # 4. 从库里重新读生成结果
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT report_date, overview, report_json FROM daily_reports WHERE report_date = ?",
                (report_date,),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return {"error": f"生成完成，但未在 daily_reports 找到 {report_date} 的记录"}

        return {
            "report_date": row["report_date"],
            "overview": row["overview"],
            "content": row["report_json"],
            "generated": True,
        }

    except Exception as e:
        return {"error": f"生成日报失败: {e}"}
    
if __name__ == "__main__":
    mcp.run(transport="stdio")