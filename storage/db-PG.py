# storage/db.py
import os
import psycopg
from psycopg.rows import dict_row

PG_DSN = os.getenv("PG_DSN", "postgresql://news:news_pwd@localhost:5432/news_db")

def get_connection():
    return psycopg.connect(PG_DSN, row_factory=dict_row)

def fetch_by_status(conn, status, limit=None):
    statuses = [status] if isinstance(status, str) else list(status)
    sql = """
        SELECT id, url, title, content, summary, source,
               published, published_ts, crawl_time, status
        FROM news
        WHERE status = ANY(%s) AND is_duplicate = 0
        ORDER BY published_ts DESC
    """
    params = [statuses]
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()  # dict_row 已经是 dict 列表

def update_fields(conn, news_id, fields: dict):
    import json
    if "keywords" in fields and isinstance(fields["keywords"], list):
        fields["keywords"] = json.dumps(fields["keywords"], ensure_ascii=False)
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [news_id]
    with conn.cursor() as cur:
        cur.execute(f"UPDATE news SET {set_clause} WHERE id = %s", values)
    conn.commit()

def query_news(conn, category=None, keyword=None, min_importance=None, limit=20):
    sql = "SELECT id, title, summary, source, category, llm_category, keywords, importance, published FROM news WHERE is_duplicate=0 AND status='analyzed'"
    params = []
    if category:
        sql += " AND llm_category = %s"; params.append(category)
    if keyword:
        sql += " AND (title ILIKE %s OR summary ILIKE %s)"; params += [f"%{keyword}%"]*2
    if min_importance:
        sql += " AND importance >= %s"; params.append(min_importance)
    sql += " ORDER BY published_ts DESC LIMIT %s"; params.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()