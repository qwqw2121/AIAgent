# storage/trend_repo.py
"""趋势统计 + 关键词归一化"""
import json
from collections import Counter

from storage.connection import (
    DONE_STATUSES, SUMMARY_EXPR, all_dicts, get_connection,
)

# 别名 -> 标准名（key 统一小写比较）
_KEYWORD_ALIASES = {
    "ai代理": "AI Agent",
    "ai智能体": "AI Agent",
    "al agent": "AI Agent",
    "ai agent": "AI Agent",
    "ai agents": "AI Agent",
    "智能体": "AI Agent",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "具身智能": "具身智能",
    "embodied ai": "具身智能",
}


def normalize_keyword(k: str) -> str:
    k = k.strip()
    return _KEYWORD_ALIASES.get(k.lower(), k)


def fetch_trends(days: int = 30) -> dict:
    """过去 N 天趋势总览：统计数字、热门技术、每日数量、重要事件"""
    ph = ",".join("?" * len(DONE_STATUSES))
    since = f"-{days} days"
    conn = get_connection()
    try:
        # 1. 核心统计
        row = conn.execute(
            f"""SELECT COUNT(*),
                       SUM(CASE WHEN importance >= 7 THEN 1 ELSE 0 END),
                       COUNT(DISTINCT llm_category)
                FROM news
                WHERE is_duplicate = 0 AND status IN ({ph})
                  AND published >= date('now', ?)""",
            (*DONE_STATUSES, since),
        ).fetchone()
        total_news = row[0] or 0
        important_news = row[1] or 0
        hot_directions = row[2] or 0

        # 2. 每日数量
        daily_counts = [
            {"date": r[0], "count": r[1]}
            for r in conn.execute(
                f"""SELECT substr(published, 1, 10) AS d, COUNT(*)
                    FROM news
                    WHERE is_duplicate = 0 AND status IN ({ph})
                      AND published >= date('now', ?)
                    GROUP BY d ORDER BY d""",
                (*DONE_STATUSES, since),
            ).fetchall()
        ]

        # 3. 热门技术：keywords 是 JSON 字符串，统计词频
        counter: Counter = Counter()
        for (kw_json,) in conn.execute(
            f"""SELECT keywords FROM news
                WHERE is_duplicate = 0 AND status IN ({ph})
                  AND published >= date('now', ?)""",
            (*DONE_STATUSES, since),
        ).fetchall():
            try:
                kws = json.loads(kw_json) if kw_json else []
                if isinstance(kws, list):
                    counter.update({normalize_keyword(k) for k in kws
                                    if isinstance(k, str) and k.strip()})
            except (json.JSONDecodeError, TypeError):
                continue
        hot_tech = [{"name": k, "count": v} for k, v in counter.most_common(8)]

        # 4. 重要事件：最近 7 份日报里的事件，取前 10 个
        events = []
        for (report_json,) in conn.execute(
            "SELECT report_json FROM daily_reports ORDER BY report_date DESC LIMIT 7"
        ).fetchall():
            try:
                for ev in (json.loads(report_json).get("events") or []):
                    events.append({"rank": len(events) + 1, "title": ev.get("title", "")})
                    if len(events) >= 10:
                        break
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
            if len(events) >= 10:
                break

        # 5. 主要事件数
        main_events = len({e["title"] for e in events})

        return {
            "days": days,
            "total_news": total_news,
            "important_news": important_news,
            "main_events": main_events,
            "hot_directions": hot_directions,
            "hot_tech": hot_tech,
            "daily_counts": daily_counts,
            "events": events,
        }
    finally:
        conn.close()


def _has_keyword(kw_json, name: str) -> bool:
    try:
        kws = json.loads(kw_json) if kw_json else []
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(kws, list) and any(
        isinstance(k, str) and k.strip() and normalize_keyword(k) == name for k in kws
    )


def fetch_tech_news(name: str, days: int = 30, limit: int = 200, offset: int = 0) -> dict:
    """某个热门技术在过去 N 天的完整新闻，口径与 hot_tech.count 一致"""
    ph = ",".join("?" * len(DONE_STATUSES))
    since = f"-{days} days"
    conn = get_connection()
    try:
        cur = conn.execute(
            f"""SELECT id, title, source, published, published_ts, {SUMMARY_EXPR},
                       llm_category, keywords, importance, url
                FROM news
                WHERE is_duplicate = 0 AND status IN ({ph})
                  AND published >= date('now', ?)
                ORDER BY published_ts DESC, id DESC""",
            (*DONE_STATUSES, since),
        )
        # 全取后在 Python 里精确匹配，和 hot_tech 的计数规则完全相同
        matched = [d for d in all_dicts(cur) if _has_keyword(d["keywords"], name)]
        return {
            "name": name,
            "days": days,
            "total": len(matched),
            "items": matched[offset: offset + limit],
        }
    finally:
        conn.close()