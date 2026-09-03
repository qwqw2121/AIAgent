# backend/main.py
import sys
from pathlib import Path
from datetime import date, datetime

# 添加项目根目录到 sys.path（而不是 backend 目录）
ROOT_DIR = Path(__file__).parent.parent  # 这会得到 /mnt/d/AIProject/ai-news-agent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException, Query
from backend.db import DB_PATH
from backend.api.news import router as news_router
from backend.api.dashboard import router as dashboard_router
from backend.api.sources import router as sources_router
from backend.api.events import router as events_router
from backend.api.reports import router as reports_router
from backend.api.rag import router as rag_router
import sqlite3
from fastapi import HTTPException
import json
from datetime import date

app = FastAPI(title="AI News Agent API", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(news_router)
app.include_router(dashboard_router)
app.include_router(sources_router)
app.include_router(events_router)
app.include_router(reports_router)
app.include_router(rag_router)


def enrich_report_news(report):
    """Use the stored news records to provide readable details for each event."""
    if not isinstance(report, dict):
        return report

    events = report.get("events", [])
    if not isinstance(events, list):
        return report

    news_ids = {
        news_id
        for event in events
        if isinstance(event, dict)
        for news_id in event.get("news_ids", [])
        if isinstance(news_id, int)
    }
    if not news_ids:
        return report

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in news_ids)
    cursor.execute(f"""
        SELECT id, title, source, published, summary, content,
               llm_category, keywords, importance, url
        FROM news
        WHERE id IN ({placeholders})
    """, tuple(news_ids))
    columns = [description[0] for description in cursor.description]
    news_by_id = {
        row[0]: dict(zip(columns, row))
        for row in cursor.fetchall()
    }
    conn.close()

    for event in events:
        if not isinstance(event, dict):
            continue
        event["news"] = [
            news_by_id[news_id]
            for news_id in event.get("news_ids", [])
            if news_id in news_by_id
        ]

    return report


def report_response(row):
    report = enrich_report_news(json.loads(row[2]))
    return {
        "date": row[0],
        "overview": row[1],
        "report": report,
    }

@app.get("/")
def root():
    return {"name": "AI News Agent API", "status": "running", "db": str(DB_PATH), "db_exists": Path(DB_PATH).exists()}

@app.get("/api/health")
def health():
    return {"status": "ok", "db_exists": Path(DB_PATH).exists(), "db_path": str(DB_PATH)}

@app.get("/api/daily-report/today")
def get_today_daily_report():

    today = date.today().isoformat()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            report_date,
            overview,
            report_json
        FROM daily_reports
        WHERE report_date = ?
    """, (today,))

    row = cursor.fetchone()

    conn.close()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="今日日报尚未生成"
        )

    return report_response(row)

@app.get("/api/daily-report/range")
def get_daily_report_range(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD")
):
    """获取日期范围内已经生成的日报。"""
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="日期格式错误，请使用 YYYY-MM-DD 格式"
        )

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT report_date, overview, report_json
        FROM daily_reports
        WHERE report_date >= ? AND report_date <= ?
        ORDER BY report_date DESC
    """, (start_date, end_date))
    rows = cursor.fetchall()
    conn.close()

    return [report_response(row) for row in rows]


@app.get("/api/daily-report/{report_date}")
def get_daily_report(report_date: str):
    """
    获取指定日期的日报
    
    参数:
        report_date: 日期字符串，格式 YYYY-MM-DD，例如 2026-08-15
    
    返回:
        该日期的日报数据
    """
    # 验证日期格式
    try:
        datetime.strptime(report_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="日期格式错误，请使用 YYYY-MM-DD 格式，例如 2026-08-15"
        )
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT
            report_date,
            overview,
            report_json
        FROM daily_reports
        WHERE report_date = ?
    """, (report_date,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"未找到 {report_date} 的日报"
        )
    
    return report_response(row)
import uvicorn
# 关键：必须有这一段
if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",  # 或者直接用 app 对象
        host="0.0.0.0",
        port=8000,
        reload=True
    )