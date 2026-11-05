
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from backend.deps import get_db
from backend.services.daily_report_service import (
    report_response,
    validate_date,
)
from storage.db import (
    fetch_all_report_indexes,
    fetch_latest_report,
    fetch_report_by_date,
    fetch_reports_range,
)

router = APIRouter(
    prefix="/api/daily-report",
    tags=["daily-report"],
)


def _today() -> str:
    """项目统一使用 UTC 日期。"""
    return datetime.now(timezone.utc).date().isoformat()


def _load_report_json(row) -> dict:
    """安全读取数据库中的 report_json。"""
    try:
        data = json.loads(row["report_json"])
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError, KeyError):
        return {}


def render_markdown(row) -> str:
    """
    按 daily_reports.report_json 的实际结构渲染完整 Markdown。

    report_json:
    {
        "overview": "...",
        "events": [
            {
                "event_id": 123,
                "title": "...",
                "summary": "...",
                "why_it_matters": "...",
                "news_ids": [1, 2],
                "news": [
                    {
                        "id": 1,
                        "title": "...",
                        "source": "...",
                        "published": "...",
                        "url": "..."
                    }
                ]
            }
        ]
    }
    """
    data = _load_report_json(row)

    overview = row["overview"] or data.get("overview", "")
    events = data.get("events", [])

    if not isinstance(events, list):
        events = []

    lines = [
        f"# AI 日报 {row['report_date']}",
        "",
    ]

    if overview:
        lines.extend([
            "## 今日概览",
            "",
            str(overview),
            "",
        ])

    for index, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            continue

        title = event.get("title") or "未命名事件"
        summary = event.get("summary") or ""
        why_it_matters = event.get("why_it_matters") or ""
        news_list = event.get("news") or []

        lines.extend([
            f"## {index}. {title}",
            "",
        ])

        if summary:
            lines.extend([
                "### 事件摘要",
                "",
                str(summary),
                "",
            ])

        if why_it_matters:
            lines.extend([
                "### 事件影响",
                "",
                str(why_it_matters),
                "",
            ])

        valid_news = [
            news for news in news_list
            if isinstance(news, dict)
        ]

        if valid_news:
            lines.extend([
                "### 相关新闻",
                "",
            ])

            for news in valid_news:
                news_title = news.get("title") or "未命名新闻"
                source = news.get("source") or ""
                url = news.get("url") or ""
                published = news.get("published") or ""

                label = (
                    f"{news_title}（{source}）"
                    if source
                    else news_title
                )

                if url:
                    lines.append(f"- [{label}]({url})")
                else:
                    lines.append(f"- {label}")

                if published:
                    lines.append(f"  - 发布时间：{published}")

            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# 1. 获取 UTC 今日日报
@router.get("/today")
def get_today_daily_report(conn=Depends(get_db)):
    row = fetch_report_by_date(conn, _today())

    if not row:
        raise HTTPException(
            status_code=404,
            detail="今日日报尚未生成",
        )

    return report_response(conn, row)


# 2. 获取最新日报
@router.get("/latest")
def get_latest_daily_report(conn=Depends(get_db)):
    row = fetch_latest_report(conn)

    if not row:
        raise HTTPException(
            status_code=404,
            detail="暂无日报",
        )

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

    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="开始日期不能晚于结束日期",
        )

    rows = fetch_reports_range(conn, start_date, end_date)

    return [
        report_response(conn, row)
        for row in rows
    ]


# 4. 获取日报索引
@router.get("/index")
def get_daily_report_index(conn=Depends(get_db)):
    rows = fetch_all_report_indexes(conn)

    result = []

    for row in rows:
        data = _load_report_json(row)
        events = data.get("events", [])

        event_count = len(events) if isinstance(events, list) else 0

        result.append({
            "date": row["report_date"],
            "overview": row["overview"],
            "event_count": event_count,
        })

    return result

from agent.graph import is_report_generating
# 5. 日报状态
# 不维护内存状态，只根据数据库判断。
# 生成期间尚未保存时返回 none；保存完成后返回 ready。
@router.get("/status")
def get_report_status(
    date: str = Query(..., description="YYYY-MM-DD"),
    conn=Depends(get_db),
):
    validate_date(date)

    # 先检查是否正在生成
    if is_report_generating(date):
        return {
            "status": "generating",
            "date": date,
        }

    # 再检查数据库
    row = fetch_report_by_date(conn, date)

    if row:
        return {
            "status": "ready",
            "date": date,
        }

    return {
        "status": "none",
        "date": date,
    }


# 6. 下载完整日报 Markdown
@router.get("/{report_date}/download")
def download_report(
    report_date: str,
    conn=Depends(get_db),
):
    validate_date(report_date)

    row = fetch_report_by_date(conn, report_date)

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"未找到 {report_date} 的日报",
        )

    markdown = render_markdown(row)

    return Response(
        content=markdown.encode("utf-8-sig"),
        media_type="text/markdown",
        headers={
            "Content-Disposition": (
                f'attachment; filename="ai-news-report-{report_date}.md"'
            )
        },
    )


# 7. 获取指定日期日报
# 动态路由放在静态路由之后
@router.get("/{report_date}")
def get_daily_report(
    report_date: str,
    conn=Depends(get_db),
):
    validate_date(report_date)

    row = fetch_report_by_date(conn, report_date)

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"未找到 {report_date} 的日报",
        )

    return report_response(conn, row)
