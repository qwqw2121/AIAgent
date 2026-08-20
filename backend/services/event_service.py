from backend.db import get_connection, table_exists


def list_events():
    conn = get_connection()
    candidates = ["events", "event_clusters", "news_events"]
    table = next((name for name in candidates if table_exists(conn, name)), None)
    if not table:
        conn.close()
        return {
            "implemented": False,
            "message": "事件聚类已在项目中完成计算，但当前还没有检测到用于网页展示的事件表。把聚类结果持久化后，这里会直接展示事件与关联新闻。",
            "data": [],
        }
    rows = [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT 50").fetchall()]
    conn.close()
    return {"implemented": True, "data": rows}
