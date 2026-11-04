from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
import json
from backend.deps import get_db
from storage.db import (
    fetch_report_by_date,
    fetch_reports_range,
)
from backend.services.daily_report_service import (
    report_response,
    validate_date,
)

router = APIRouter(
    prefix="/api/daily-report",
    tags=["daily-report"]
)


# 1. 获取今日日报
@router.get("/today")
def get_today_daily_report(conn=Depends(get_db)):
    d = datetime.now(timezone.utc).date().isoformat()

    row = fetch_report_by_date(conn, d)

    if not row:
        raise HTTPException(404, "今日日报尚未生成")

    return report_response(conn, row)

from storage.db import fetch_latest_report
# 2. 获取最新日报
@router.get("/latest")
def get_latest_daily_report(conn=Depends(get_db)):
    row = fetch_latest_report(conn)

    if not row:
        raise HTTPException(404, "暂无日报")

    return report_response(conn, row)


# 3. 获取日期范围内的日报
@router.get("/range")
def get_daily_report_range(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    conn=Depends(get_db),
):
    validate_date(start_date)
    validate_date(end_date)

    rows = fetch_reports_range(conn, start_date, end_date)

    return [
        report_response(conn, row)
        for row in rows
    ]

from storage.db import fetch_all_report_indexes
# 4. 获取日报索引
@router.get("/index")
def get_daily_report_index(conn=Depends(get_db)):
    rows = fetch_all_report_indexes(conn)

    out = []

    for row in rows:
        try:
            event_count = len(
                json.loads(row["report_json"]).get("events", [])
            )
        except (ValueError, TypeError):
            event_count = 0

        out.append({
            "date": row["report_date"],
            "overview": row["overview"],
            "event_count": event_count,
        })

    return out


# 5. 获取指定日期日报
# 动态路由放在静态路由之后
@router.get("/{report_date}")
def get_daily_report(
    report_date: str,
    conn=Depends(get_db)
):
    validate_date(report_date)

    row = fetch_report_by_date(conn, report_date)

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"未找到 {report_date} 的日报"
        )

    return report_response(conn, row)