# backend/api/dashboard.py（或新建 backend/api/trends.py，在 main.py 中 include_router）
# 前端 /trends 和 /important 两个页面依赖这两个接口

import json
import sqlite3
from collections import Counter
from fastapi import APIRouter, Query
from storage.db import get_connection

router = APIRouter(prefix="/api", tags=["trends"])


@router.get("/trends")
def get_trends(days: int = Query(30, ge=1, le=90)):
    """过去 N 天趋势总览：统计数字、热门技术、每日数量、重要事件"""
    conn = get_connection()
    try:
        # 1. 核心统计（近 N 天、非重复、已分析的新闻）
        row = conn.execute(
            """SELECT COUNT(*),
                      SUM(CASE WHEN importance >= 7 THEN 1 ELSE 0 END),
                      COUNT(DISTINCT llm_category)
               FROM news
               WHERE is_duplicate = 0 AND status IN ('analyzed', 'embedded')
                 AND published >= date('now', ?)""",
            (f"-{days} days",),
        ).fetchone()
        total_news = row[0] or 0
        important_news = row[1] or 0
        hot_directions = row[2] or 0

        # 2. 每日数量（用于趋势图）
        daily_counts = [
            {"date": r[0], "count": r[1]}
            for r in conn.execute(
                """SELECT published, COUNT(*) FROM news
                   WHERE is_duplicate = 0 AND status = 'analyzed'
                     AND published >= date('now', ?)
                   GROUP BY published ORDER BY published""",
                (f"-{days} days",),
            ).fetchall()
        ]

        # 3. 热门技术：keywords 是 JSON 字符串，解析后统计词频
        counter: Counter = Counter()
        for (kw_json,) in conn.execute(
            """SELECT keywords FROM news
               WHERE is_duplicate = 0 AND status IN ('analyzed', 'embedded')
                 AND published >= date('now', ?)""",
            (f"-{days} days",),
        ).fetchall():
            try:
                counter.update(json.loads(kw_json) if kw_json else [])
            except (json.JSONDecodeError, TypeError):
                continue
        hot_tech = [{"name": k, "count": v} for k, v in counter.most_common(8)]

        # 4. 重要事件：取近期聚合日报中 importance 最高的事件
        events = []
        rank = 1
        for (report_json,) in conn.execute(
            "SELECT report_json FROM daily_reports ORDER BY report_date DESC LIMIT 7"
        ).fetchall():
            try:
                for ev in (json.loads(report_json).get("events") or []):
                    events.append({"rank": rank, "title": ev.get("title", "")})
                    rank += 1
                    if rank > 10:
                        break
            except (json.JSONDecodeError, TypeError):
                continue
            if rank > 10:
                break

        # 5. 主要事件数：去重后的独立事件标题数
        main_events = len({e["title"] for e in events}) if events else 0

        return {
            "days": days,
            "total_news": total_news,
            "important_news": important_news,
            "main_events": main_events,
            "hot_directions": hot_directions,
            "hot_tech": hot_tech,
            "daily_counts": daily_counts,
            "events": events[:10],
        }
    finally:
        conn.close()


@router.get("/news/important")
def get_important_news(min_importance: int = Query(7, ge=1, le=10), limit: int = Query(50, le=200)):
    """重要新闻列表（/important 页面用）"""
    conn = get_connection()
    try:
        cur = conn.execute(
            """SELECT id, title, summary, source, url, llm_category, importance, published
               FROM news
               WHERE is_duplicate = 0 AND status IN ('analyzed', 'embedded') AND importance >= ?
               ORDER BY importance DESC, published_ts DESC LIMIT ?""",
            (min_importance, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()