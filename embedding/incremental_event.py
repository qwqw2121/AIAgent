# embedding/incremental_event.py
"""
增量事件聚类

逻辑：
1. 按发布时间顺序处理 status='embedded' 且未去重的新闻
2. importance <= MIN_NEWS_IMPORTANCE 的新闻不参与聚类，直接标记为 'unclustered'
3. 对每条新闻，在向量库中找最近邻（先 30 条，不够再扩大到 90）
4. 在时间窗口 [published_ts - JOIN_WINDOW_DAYS, published_ts] 内，
   找已经归属事件的近邻，取相似度最高的事件加入
5. 找不到则创建新事件（此时是 1 条的"候选事件"，等待后续新闻并入）
6. 更新事件统计信息与代表新闻
7. 主聚类完成后，把单条事件并入附近已有 >=2 条新闻的事件
8. 最后释放过期的小事件：超出时间窗口、再也等不到新邻居、仍不足
   MIN_EVENT_SIZE 条的事件，其新闻标记为 'unclustered'，不再等待

注意：事件表中允许存在 <MIN_EVENT_SIZE 条的候选事件，
日报和前端只应展示 news_count >= MIN_EVENT_SIZE 的事件。
"""

from typing import NamedTuple, Optional

from storage.db import get_connection
from embedding.vector_store import get_vector_store
from pipeline.config import (
    MIN_NEWS_IMPORTANCE, MIN_EVENT_SIZE, SINGLE_EVENT_MIN_IMPORTANCE,
)


# =========================================================
# 配置
# =========================================================

EVENT_THRESHOLD = 0.75          # 主聚类相似度阈值
N_RESULTS = 30                  # 第一次近邻查询数量
N_RESULTS_EXPANDED = 90         # 第一次没找到已归属事件时，扩大查询
JOIN_WINDOW_DAYS = 3            # 向前看多少天的已有事件

MERGE_THRESHOLD = 0.65          # 单条事件并入其他事件的相似度阈值
MERGE_TARGET_MIN_SIZE = 1       # 并入目标至少已有 2 条（并入后即达到 3 条）

vector_store = get_vector_store()


# =========================================================
# 数据结构
# =========================================================

class Candidate(NamedTuple):
    kind: str                               # "joined" | "new" | "no_embedding"
    event_id: Optional[int] = None
    similarity: Optional[float] = None


# =========================================================
# 向量工具
# =========================================================

def _space() -> str:
    """读取集合的距离空间，默认 cosine。"""
    metadata = getattr(vector_store.collection, "metadata", None) or {}
    space = metadata.get("hnsw:space", "cosine")
    return str(space).lower()


def _dist_to_similarity(dist: float, space: str) -> float:
    """
    Chroma query 返回的是距离，按空间转成相似度：
    - cosine: distance = 1 - cosine_similarity
    - l2:     distance = 欧氏距离，用 1 / (1 + d) 映射到 (0, 1]
    - ip:     内积距离，越大越相似，直接取负距离
    """
    if space == "cosine":
        return 1.0 - float(dist)
    if space == "l2":
        return 1.0 / (1.0 + float(dist))
    if space == "ip":
        return -float(dist)
    return 1.0 - float(dist)


def _get_embedding(news_id: int) -> Optional[list]:
    res = vector_store.collection.get(
        ids=[str(news_id)],
        include=["embeddings"],
    )
    embeddings = res.get("embeddings")
    if embeddings is None or len(embeddings) == 0:
        return None
    return embeddings[0]


# =========================================================
# 事件统计与代表新闻
# =========================================================

def _update_event(conn, event_id: int) -> None:
    """
    重新计算并更新事件的 news_count / 时间范围 / 重要性。
    时间范围用 published_ts 计算，避免 ISO 字符串跨时区比较出错。
    """
    row = conn.execute("""
        SELECT COUNT(*), MIN(n.published_ts), MAX(n.published_ts), MAX(n.importance)
        FROM event_news en
        JOIN news n ON en.news_id = n.id
        WHERE en.event_id = ?
    """, (event_id,)).fetchone()

    count, first_ts, last_ts, importance = row

    first_published = None
    last_published = None
    if first_ts is not None:
        first_published = conn.execute(
            "SELECT published FROM news WHERE published_ts = ? LIMIT 1",
            (first_ts,),
        ).fetchone()
        first_published = first_published[0] if first_published else None
    if last_ts is not None:
        last_published = conn.execute(
            "SELECT published FROM news WHERE published_ts = ? LIMIT 1",
            (last_ts,),
        ).fetchone()
        last_published = last_published[0] if last_published else None

    conn.execute("""
        UPDATE events
        SET news_count = ?,
            first_published = ?,
            last_published = ?,
            importance = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (count, first_published, last_published, importance or 0, event_id))


def _refresh_representative(conn, event_id: int) -> None:
    """
    选择代表新闻：
    1. importance 最高
    2. 发布时间最早（打破平局）
    并同步更新 events.event_name
    """
    row = conn.execute("""
        SELECT n.id, n.title
        FROM event_news en
        JOIN news n ON en.news_id = n.id
        WHERE en.event_id = ?
        ORDER BY COALESCE(n.importance, 0) DESC, n.published_ts ASC
        LIMIT 1
    """, (event_id,)).fetchone()

    if not row:
        return

    rep_id, rep_title = row

    conn.execute("""
        UPDATE event_news
        SET is_representative = CASE WHEN news_id = ? THEN 1 ELSE 0 END
        WHERE event_id = ?
    """, (rep_id, event_id))

    conn.execute("""
        UPDATE events
        SET event_name = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (rep_title or "未命名事件", event_id))


def _create_event(conn, news_id: int) -> Optional[int]:
    """用一条新闻创建新事件（候选事件），并设为代表"""
    row = conn.execute("""
        SELECT title, summary, llm_category, keywords, importance, published
        FROM news
        WHERE id = ?
    """, (news_id,)).fetchone()

    if not row:
        return None

    cur = conn.execute("""
        INSERT INTO events (
            event_name, summary, category, keywords, importance,
            news_count, first_published, last_published
        )
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
    """, (
        row[0] or "未命名事件",
        row[1] or "",
        row[2] or "",
        row[3] or "",
        row[4] or 0,
        row[5],
        row[5],
    ))

    event_id = cur.lastrowid

    conn.execute("""
        INSERT INTO event_news (event_id, news_id, similarity, is_representative)
        VALUES (?, ?, 1.0, 1)
    """, (event_id, news_id))

    return event_id


# =========================================================
# 向量近邻查询
# =========================================================

def _query_sims(
    news_id: int,
    embedding: list,
    n_results: int,
    threshold: float = EVENT_THRESHOLD,
) -> dict[int, float]:
    """
    在向量库中查询近邻，返回 {news_id: similarity}。
    只保留相似度 >= threshold 且不是自己的结果。
    """
    result = vector_store.collection.query(
        query_embeddings=[embedding],
        n_results=n_results,
    )

    ids = (result.get("ids") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    space = _space()
    sims: dict[int, float] = {}

    for sid, dist in zip(ids, distances):
        sid = int(sid)
        if sid == news_id:
            continue
        similarity = _dist_to_similarity(dist, space)
        if similarity >= threshold:
            sims[sid] = similarity

    return sims


def _lookup_events(conn, sims: dict[int, float], lo_ts: int, hi_ts: int) -> list[tuple[int, int]]:
    """
    在相似新闻中，找出已经归属事件、且发布时间在窗口内的记录。
    返回 [(news_id, event_id), ...]
    """
    if not sims:
        return []

    placeholders = ",".join("?" * len(sims))
    rows = conn.execute(f"""
        SELECT en.news_id, en.event_id
        FROM event_news en
        JOIN news n ON n.id = en.news_id
        WHERE en.news_id IN ({placeholders})
          AND n.published_ts >= ?
          AND n.published_ts <= ?
    """, (*sims.keys(), lo_ts, hi_ts)).fetchall()

    return rows


def _best_candidate(conn, news_id: int, published_ts: int) -> Candidate:
    """
    寻找最佳已有事件。
    先查 N_RESULTS 个近邻，若其中没有已归属事件的，再扩大到 N_RESULTS_EXPANDED。
    """
    embedding = _get_embedding(news_id)
    if embedding is None:
        return Candidate(kind="no_embedding")

    lo_ts = published_ts - JOIN_WINDOW_DAYS * 86400
    hi_ts = published_ts

    for n in (N_RESULTS, N_RESULTS_EXPANDED):
        sims = _query_sims(news_id, embedding, n)
        rows = _lookup_events(conn, sims, lo_ts, hi_ts)

        if rows:
            best_news_id, best_event_id = max(rows, key=lambda r: sims[r[0]])
            return Candidate(
                kind="joined",
                event_id=best_event_id,
                similarity=sims[best_news_id],
            )

    return Candidate(kind="new")


# =========================================================
# 单条事件合并
# =========================================================

def _merge_singletons(conn, start_ts: Optional[int] = None, end_ts: Optional[int] = None) -> dict:
    """
    把只有 1 条新闻的事件，并入时间窗口内已有 >= MERGE_TARGET_MIN_SIZE 条新闻的事件。
    相似度 >= MERGE_THRESHOLD。
    用向量库近邻查询代替全量取 embedding，避免 O(N*M) 的 Python 计算。
    """
    sql = """
        SELECT e.id, en.news_id, n.published_ts
        FROM events e
        JOIN event_news en ON en.event_id = e.id
        JOIN news n ON n.id = en.news_id
        WHERE e.news_count = 1
    """
    params: list = []

    if start_ts is not None:
        sql += " AND n.published_ts >= ? AND n.published_ts < ?"
        params.extend([start_ts, end_ts])

    singles = conn.execute(sql, params).fetchall()

    merged = 0
    kept = 0
    window = JOIN_WINDOW_DAYS * 86400

    for event_id, news_id, pts in singles:
        # 前面的循环可能已经改动过这个事件，重新确认
        cnt = conn.execute(
            "SELECT news_count FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if not cnt or cnt[0] != 1 or pts is None:
            continue

        emb = _get_embedding(news_id)
        if emb is None:
            kept += 1
            continue

        sims = _query_sims(news_id, emb, N_RESULTS_EXPANDED, threshold=MERGE_THRESHOLD)
        if not sims:
            kept += 1
            continue

        marks = ",".join("?" * len(sims))
        rows = conn.execute(f"""
            SELECT en.news_id, en.event_id
            FROM event_news en
            JOIN news n ON n.id = en.news_id
            JOIN events e ON e.id = en.event_id
            WHERE en.news_id IN ({marks})
              AND en.event_id != ?
              AND e.news_count >= ?
              AND n.published_ts BETWEEN ? AND ?
        """, (*sims.keys(), event_id, MERGE_TARGET_MIN_SIZE,
              pts - window, pts + window)).fetchall()

        if not rows:
            kept += 1
            continue

        best_news_id, best_event_id = max(rows, key=lambda r: sims[r[0]])
        best_similarity = sims[best_news_id]

        conn.execute("""
            UPDATE event_news
            SET event_id = ?, similarity = ?, is_representative = 0
            WHERE news_id = ? AND event_id = ?
        """, (best_event_id, best_similarity, news_id, event_id))

        # 单条事件的唯一新闻已移走，事件必为空
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))

        _update_event(conn, best_event_id)
        _refresh_representative(conn, best_event_id)
        merged += 1

    conn.commit()
    return {"merged": merged, "kept": kept}


# =========================================================
# 释放过期的小事件
# =========================================================

def _release_stale_small_events(conn, end_ts: Optional[int]) -> int:
    """
    小事件（news_count < MIN_EVENT_SIZE）如果最新一条新闻已超出时间窗口，
    之后的新闻不可能再并入它，其新闻标记为 'unclustered'，不再停留在 clustered。
    返回释放的新闻条数。
    """
    if end_ts is None:
        return 0

    cutoff = end_ts - JOIN_WINDOW_DAYS * 86400
    cur = conn.execute("""
        UPDATE news
        SET status = 'unclustered'
        WHERE status = 'clustered'
          AND id IN (
              SELECT en.news_id
              FROM event_news en
              JOIN events e ON e.id = en.event_id
              WHERE e.news_count < ?
                AND e.importance < ?
                AND (
                    SELECT MAX(n2.published_ts)
                    FROM event_news en2
                    JOIN news n2 ON n2.id = en2.news_id
                    WHERE en2.event_id = e.id
                ) < ?
          )
    """, (MIN_EVENT_SIZE, SINGLE_EVENT_MIN_IMPORTANCE, cutoff))
    conn.commit()
    return cur.rowcount


# =========================================================
# 处理单篇新闻
# =========================================================

def process_news(conn, news_id: int) -> tuple[Optional[int], str]:
    """
    对单篇新闻做事件聚类。
    返回 (event_id, kind)
    kind 可能值：existing / joined / new / low_importance /
                 no_embedding / invalid_published / insert_failed / create_failed
    """
    conn.execute("BEGIN IMMEDIATE")

    row = conn.execute(
        "SELECT event_id FROM event_news WHERE news_id = ? LIMIT 1",
        (news_id,),
    ).fetchone()
    if row:
        conn.execute("UPDATE news SET status = 'clustered' WHERE id = ?", (news_id,))
        conn.commit()
        return row[0], "existing"

    row = conn.execute(
        "SELECT published_ts, importance FROM news WHERE id = ?",
        (news_id,),
    ).fetchone()
    if not row or row[0] is None:
        conn.rollback()
        return None, "invalid_published"

    published_ts, importance = row

    # 不够重要：不参与聚类，标记为终态，避免反复处理
    if importance is None or importance <= MIN_NEWS_IMPORTANCE:
        conn.execute("UPDATE news SET status = 'unclustered' WHERE id = ?", (news_id,))
        conn.commit()
        return None, "low_importance"

    cand = _best_candidate(conn, news_id, published_ts)

    if cand.kind == "no_embedding":
        conn.rollback()
        print(f"[跳过] news_id={news_id} 没有 Embedding", flush=True)
        return None, "no_embedding"

    if cand.kind == "joined":
        cur = conn.execute("""
            INSERT OR IGNORE INTO event_news (event_id, news_id, similarity, is_representative)
            VALUES (?, ?, ?, 0)
        """, (cand.event_id, news_id, cand.similarity))

        if cur.rowcount == 0:
            existing = conn.execute(
                "SELECT event_id FROM event_news WHERE news_id = ? LIMIT 1",
                (news_id,),
            ).fetchone()
            if existing:
                conn.commit()
                return existing[0], "existing"
            conn.rollback()
            return None, "insert_failed"

        _update_event(conn, cand.event_id)
        _refresh_representative(conn, cand.event_id)
        event_id, kind = cand.event_id, "joined"

    else:
        event_id = _create_event(conn, news_id)
        if event_id is None:
            conn.rollback()
            return None, "create_failed"
        kind = "new"

    conn.execute("UPDATE news SET status = 'clustered' WHERE id = ?", (news_id,))
    conn.commit()
    return event_id, kind


# =========================================================
# 批量入口
# =========================================================

def run(start_ts: Optional[int] = None, end_ts: Optional[int] = None) -> dict:
    """
    批量处理新闻。
    start_ts / end_ts 必须同时提供，或同时为 None（处理全部）。
    """
    if (start_ts is None) != (end_ts is None):
        raise ValueError("start_ts 和 end_ts 必须同时提供或同时为 None")
    if start_ts is not None and start_ts >= end_ts:
        raise ValueError("start_ts 必须小于 end_ts")

    conn = get_connection()
    try:
        sql = """
            SELECT id
            FROM news
            WHERE status = 'embedded'
              AND is_duplicate = 0
        """
        params: list = []

        if start_ts is not None:
            sql += " AND published_ts >= ? AND published_ts < ?"
            params.extend([start_ts, end_ts])

        sql += " ORDER BY published_ts, id"

        news_ids = [r[0] for r in conn.execute(sql, params)]

        new_events = joined = existing = skipped = failed = 0

        for news_id in news_ids:
            try:
                _, kind = process_news(conn, news_id)
                if kind == "new":
                    new_events += 1
                elif kind == "joined":
                    joined += 1
                elif kind == "existing":
                    existing += 1
                elif kind == "low_importance":
                    skipped += 1
                else:
                    failed += 1
            except Exception as e:
                conn.rollback()
                failed += 1
                print(f"[聚类失败] news_id={news_id}: {e}", flush=True)

        merge_stats = _merge_singletons(conn, start_ts, end_ts)
        released = _release_stale_small_events(conn, end_ts)

        result = {
            "total": len(news_ids),
            "new_events": new_events,
            "joined_existing": joined + existing,
            "skipped_low_importance": skipped,
            "failed": failed,
            "merged_singletons": merge_stats["merged"],
            "kept_singletons": merge_stats["kept"],
            "released_stale": released,
        }
        print(f"[事件聚类完成] {result}", flush=True)
        return result

    finally:
        conn.close()


# =========================================================
# 本地测试
# =========================================================

if __name__ == "__main__":
    print(run())