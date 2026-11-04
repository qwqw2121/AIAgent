import json
from datetime import datetime
from fastapi import  HTTPException
from storage.db import fetch_news_by_ids

#使用已存储的新闻记录为每个事件提供可读的详细信息。
def enrich_report_news(conn, report):
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
    news_by_id = fetch_news_by_ids(conn, news_ids)

    for event in events:
        if not isinstance(event, dict):
            continue
        event["news"] = [
            news_by_id[news_id]
            for news_id in event.get("news_ids", [])
            if news_id in news_by_id
        ]

    return report


def report_response(conn, report_row):
    """把日报记录转为响应结构（enrich 复用同一个连接）"""
    report = enrich_report_news(conn, json.loads(report_row["report_json"]))
    return {
        "date": report_row["report_date"],
        "overview": report_row["overview"],
        "report": report,
    }


def validate_date(d: str):
    try:
        datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="日期格式错误，请使用 YYYY-MM-DD 格式"
        )
