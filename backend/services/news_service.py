from datetime import datetime, timedelta
from backend.db import get_connection, table_columns


def _safe_date(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _row_to_dict(row):
    if row is None:
        return None
    item = dict(row)
    for key in ("published", "crawl_time", "created_at"):
        if key in item:
            item[key] = _safe_date(item[key])
    return item


def list_news(limit=20, offset=0, category=None, source=None, q=None, importance=None):
    conn = get_connection()
    cols = table_columns(conn, "news")
    where = ["COALESCE(is_duplicate, 0) = 0"] if "is_duplicate" in cols else ["1=1"]
    params = []

    if category:
        field = "llm_category" if "llm_category" in cols else "category"
        where.append(f"COALESCE({field}, '') = ?")
        params.append(category)
    if source and "source" in cols:
        where.append("source = ?")
        params.append(source)
    if q:
        parts = []
        for field in ("title", "summary", "content", "keywords"):
            if field in cols:
                parts.append(f"COALESCE({field}, '') LIKE ?")
                params.append(f"%{q}%")
        if parts:
            where.append("(" + " OR ".join(parts) + ")")
    if importance is not None and "importance" in cols:
        where.append("importance >= ?")
        params.append(importance)

    order = "published_ts DESC" if "published_ts" in cols else "id DESC"
    sql = f"SELECT * FROM news WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = conn.execute(sql, params).fetchall()

    count_sql = f"SELECT COUNT(*) FROM news WHERE {' AND '.join(where)}"
    total = conn.execute(count_sql, params[:-2]).fetchone()[0]
    conn.close()
    return {"data": [_row_to_dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


def get_news(news_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM news WHERE id = ?", (news_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def dashboard_stats():
    conn = get_connection()
    cols = table_columns(conn, "news")
    duplicate = "COALESCE(is_duplicate, 0) = 0" if "is_duplicate" in cols else "1=1"
    total = conn.execute(f"SELECT COUNT(*) FROM news WHERE {duplicate}").fetchone()[0]
    sources = conn.execute(f"SELECT COUNT(DISTINCT source) FROM news WHERE {duplicate} AND source IS NOT NULL AND source != ''").fetchone()[0] if "source" in cols else 0

    today_sql = "date(published) = date('now', 'localtime')" if "published" in cols else "0"
    today = conn.execute(f"SELECT COUNT(*) FROM news WHERE {duplicate} AND {today_sql}").fetchone()[0]

    important = conn.execute(
        f"SELECT COUNT(*) FROM news WHERE {duplicate} AND COALESCE(importance, 0) >= 4"
    ).fetchone()[0] if "importance" in cols else 0

    categories = []
    category_field = "llm_category" if "llm_category" in cols else ("category" if "category" in cols else None)
    if category_field:
        categories = [dict(row) for row in conn.execute(
            f"SELECT COALESCE({category_field}, '未分类') AS name, COUNT(*) AS count FROM news WHERE {duplicate} GROUP BY {category_field} ORDER BY count DESC LIMIT 8"
        ).fetchall()]

    source_rows = []
    if "source" in cols:
        source_rows = [dict(row) for row in conn.execute(
            f"SELECT COALESCE(source, '未知来源') AS name, COUNT(*) AS count FROM news WHERE {duplicate} GROUP BY source ORDER BY count DESC LIMIT 10"
        ).fetchall()]

    conn.close()
    return {
        "total_news": total,
        "today_news": today,
        "sources": sources,
        "important_news": important,
        "categories": categories,
        "sources_top": source_rows,
    }


def list_sources():
    conn = get_connection()
    rows = conn.execute(
        "SELECT source AS name, COUNT(*) AS count, MAX(published) AS latest FROM news WHERE COALESCE(is_duplicate, 0)=0 GROUP BY source ORDER BY count DESC"
    ).fetchall()
    conn.close()
    return [_row_to_dict(row) for row in rows]
