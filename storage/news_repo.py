# storage/news_repo.py
"""新闻表读写：流水线 + 后端 API"""
import json
import time

from storage.connection import (
    DONE_STATUSES, SUMMARY_EXPR, all_dicts, get_connection,
)


# ---------- 流水线用 ----------
def update_fields(conn, news_id, fields, commit=True):
    if not fields:
        return False
    fields = dict(fields)
    if isinstance(fields.get("keywords"), list):
        fields["keywords"] = json.dumps(fields["keywords"], ensure_ascii=False)
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE news SET {set_clause} WHERE id = ?",
        [*fields.values(), news_id],
    )
    if commit:
        conn.commit()
    return True


def fetch_by_status(conn, status, limit=None):
    """status 可传字符串或元组"""
    statuses = (status,) if isinstance(status, str) else tuple(status)
    marks = ",".join("?" * len(statuses))
    sql = (f"SELECT * FROM news WHERE status IN ({marks}) "
           f"AND is_duplicate = 0 ORDER BY id")
    params = list(statuses)
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return all_dicts(conn.execute(sql, params))


# ---------- 后端 API 用 ----------
def query_news(
    conn,
    category=None,
    keyword=None,
    min_importance=None,
    limit=20,
    status=("analyzed", "embedded", "clustered", "reported"),
    start_ts=None,
    end_ts=None,
):
    """
    查询新闻。

    start_ts: 发布时间下界，包含。
    end_ts: 发布时间上界，不包含。
    """

    statuses = (status,) if isinstance(status, str) else tuple(status)
    marks = ",".join("?" * len(statuses))

    sql = f"""
        SELECT id, title, source, published, published_ts, {SUMMARY_EXPR},
               llm_category, keywords, importance, url, status
        FROM news
        WHERE is_duplicate = 0
          AND status IN ({marks})
    """

    params = list(statuses)

    if category:
        sql += " AND llm_category = ?"
        params.append(category)

    if keyword:
        sql += """ AND (
            title LIKE ? COLLATE NOCASE
            OR summary LIKE ? COLLATE NOCASE
            OR llm_summary LIKE ? COLLATE NOCASE
            OR keywords LIKE ? COLLATE NOCASE
        )"""
        params += [f"%{keyword}%"] * 4

    if min_importance is not None:
        sql += " AND importance >= ?"
        params.append(min_importance)

    # 发布时间过滤：左闭右开
    if start_ts is not None:
        sql += " AND published_ts >= ?"
        params.append(int(start_ts))

    if end_ts is not None:
        sql += " AND published_ts < ?"
        params.append(int(end_ts))

    sql += " ORDER BY published_ts DESC LIMIT ?"
    params.append(limit)

    return all_dicts(conn.execute(sql, params))


def fetch_news_by_ids(conn, news_ids):
    """按 id 批量取新闻，返回 {id: dict}"""

    news_ids = list(news_ids or [])
    if not news_ids:
        return {}

    marks = ",".join("?" * len(news_ids))

    cur = conn.execute(
        f"""
        SELECT id, title, source, published, published_ts,
               {SUMMARY_EXPR}, content,
               llm_category, keywords, importance, url
        FROM news
        WHERE id IN ({marks})
        """,
        news_ids,
    )

    return {d["id"]: d for d in all_dicts(cur)}


def fetch_important_recent(limit=8, min_importance=7, hours=24):
    since = int(time.time()) - hours * 3600
    ph = ",".join("?" * len(DONE_STATUSES))
    conn = get_connection()
    try:
        rows = conn.execute(f"""
            SELECT id, title, source, published, {SUMMARY_EXPR},
                   llm_category, importance, url
            FROM news
            WHERE is_duplicate = 0
              AND importance >= ?
              AND status IN ({ph})
              AND published_ts >= ?
            ORDER BY importance DESC, published_ts DESC
            LIMIT ?
        """, (min_importance, *DONE_STATUSES, since, limit)).fetchall()
    finally:
        conn.close()
    keys = ["id", "title", "source", "published", "summary",
            "llm_category", "importance", "url"]
    return [dict(zip(keys, r)) for r in rows]