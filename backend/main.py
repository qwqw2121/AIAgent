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

    return {
        "date": row[0],
        "overview": row[1],
        "report": json.loads(row[2])
    }

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
    
    return {
        "date": row[0],
        "overview": row[1],
        "report": json.loads(row[2])
    }
# 可选：获取日期范围
@app.get("/api/daily-report/range")
def get_daily_report_range(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD")
):
    """
    获取日期范围内的日报
    
    参数:
        start_date: 开始日期，格式 YYYY-MM-DD
        end_date: 结束日期，格式 YYYY-MM-DD
    """
    # 验证日期格式
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
        SELECT
            report_date,
            overview,
            report_json
        FROM daily_reports
        WHERE report_date >= ? AND report_date <= ?
        ORDER BY report_date DESC
    """, (start_date, end_date))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            "date": row[0],
            "overview": row[1],
            "report": json.loads(row[2])
        }
        for row in rows
    ]

