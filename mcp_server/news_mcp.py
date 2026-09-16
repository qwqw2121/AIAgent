# mcp_server/news_mcp.py
import os
import sys
import json
import threading
import datetime
# 🌟 关键修复：将项目根目录加入 sys.path，确保子进程能找到 storage 模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp.server.fastmcp import FastMCP
from storage.db import get_connection, query_news, fetch_report_by_date
from storage.vectorstore import get_retriever  # 引入向量库
from pipeline.flows.daily_news_flow import daily_flow


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

    
if __name__ == "__main__":
    mcp.run(transport="stdio")