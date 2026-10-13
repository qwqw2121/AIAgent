# embedding/incremental_event.py
from storage.db import get_connection
from embedding.vector_store import VectorStore

EVENT_THRESHOLD = 0.75
N_RESULTS = 30                 # 多取一些，因为很多近邻还没有事件
JOIN_WINDOW_DAYS = 3           # 只能并入窗口开始前 N 天内的事件

vector_store = VectorStore()


def _update_event(conn, event_id):
    count, first, last, imp = conn.execute("""
        SELECT COUNT(*), MIN(n.published), MAX(n.published), MAX(n.importance)
        FROM event_news en JOIN news n ON en.news_id = n.id
        WHERE en.event_id = ?""", (event_id,)).fetchone()
    conn.execute("""
        UPDATE events SET news_count=?, first_published=?, last_published=?,
               importance=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
        (count, first, last, imp or 0, event_id))


def _create_event(conn, news_id):
    row = conn.execute("""
        SELECT title, summary, llm_category, keywords, importance, published
        FROM news WHERE id=?""", (news_id,)).fetchone()
    if not row:
        return None
    cur = conn.execute("""
        INSERT INTO events (event_name, summary, category, keywords, importance,
                            news_count, first_published, last_published)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
        (row[0] or "未命名事件", row[1] or "", row[2] or "", row[3] or "",
         row[4] or 0, row[5], row[5]))
    event_id = cur.lastrowid
    conn.execute("""
        INSERT INTO event_news (event_id, news_id, similarity, is_representative)
        VALUES (?, ?, 1.0, 1)""", (event_id, news_id))
    return event_id


def _best_candidate(conn, news_id, lo_ts, hi_ts):
    """返回 (event_id, similarity) 或 None"""
    res = vector_store.collection.get(ids=[str(news_id)], include=["embeddings"])
    embs = res["embeddings"]
    if embs is None or len(embs) == 0:
        return "no_embedding"

    q = vector_store.collection.query(query_embeddings=[embs[0]], n_results=N_RESULTS)
    sims = {}
    for sid, dist in zip(q["ids"][0], q["distances"][0]):
        sid = int(sid)
        s = 1 - dist
        if sid != news_id and s >= EVENT_THRESHOLD:
            sims[sid] = s
    if not sims:
        return None

    marks = ",".join("?" * len(sims))
    rows = conn.execute(f"""
        SELECT en.news_id, en.event_id
        FROM event_news en JOIN news n ON n.id = en.news_id
        WHERE en.news_id IN ({marks})
          AND n.published_ts >= ? AND n.published_ts < ?
    """, (*sims.keys(), lo_ts, hi_ts)).fetchall()
    if not rows:
        return None
    nid, eid = max(rows, key=lambda r: sims[r[0]])
    return eid, sims[nid]


def process_news(conn, news_id, lo_ts, hi_ts):
    row = conn.execute("SELECT event_id FROM event_news WHERE news_id=?", (news_id,)).fetchone()
    if row:
        conn.execute("UPDATE news SET status='clustered' WHERE id=?", (news_id,))
        conn.commit()
        return row[0], "existing"

    cand = _best_candidate(conn, news_id, lo_ts, hi_ts)
    if cand == "no_embedding":
        print(f"news_id={news_id} 没有Embedding")
        return None, "no_embedding"

    if cand:
        event_id, sim = cand
        conn.execute("""INSERT OR IGNORE INTO event_news (event_id, news_id, similarity)
                        VALUES (?, ?, ?)""", (event_id, news_id, sim))
        _update_event(conn, event_id)
        kind = "joined"
    else:
        event_id = _create_event(conn, news_id)
        kind = "new"

    conn.execute("UPDATE news SET status='clustered' WHERE id=?", (news_id,))
    conn.commit()          # 事件、关系、状态在同一个事务里，要么全成功要么全回滚
    return event_id, kind


def run(start_ts=None, end_ts=None):
    conn = get_connection()
    try:
        sql = "SELECT id FROM news WHERE status='embedded' AND is_duplicate=0"
        params = []
        if start_ts is not None:
            sql += " AND published_ts >= ? AND published_ts < ?"
            params = [start_ts, end_ts]
        sql += " ORDER BY published_ts, id"
        news_ids = [r[0] for r in conn.execute(sql, params)]

        lo = (start_ts - JOIN_WINDOW_DAYS * 86400) if start_ts is not None else 0
        hi = end_ts if end_ts is not None else 2**62

        new_events = joined = existing = failed = 0
        for news_id in news_ids:
            try:
                _, kind = process_news(conn, news_id, lo, hi)
                if kind == "new":
                    new_events += 1
                elif kind == "joined":
                    joined += 1
                elif kind == "existing":
                    existing += 1
                else:
                    failed += 1
            except Exception as e:
                conn.rollback()
                failed += 1
                print(f"[失败] news_id={news_id}: {e}", flush=True)

        return {"total": len(news_ids), "new_events": new_events,
                "joined_existing": joined + existing, "failed": failed}
    finally:
        conn.close()