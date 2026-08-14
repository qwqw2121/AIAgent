'''
新新闻
 ↓
Chroma
 ↓
找到相似新闻
 ↓
找到对应 event
 ↓
similarity >= 0.75
      ↓
加入已有事件

similarity < 0.75
      ↓
创建新事件
'''

# embedding/incremental_event.py

import sqlite3
from pathlib import Path

from vector_store import VectorStore


DB_PATH = (
    Path(__file__).parent.parent
    / "storage"
    / "news.db"
)

# 事件匹配阈值
EVENT_THRESHOLD = 0.75


vector_store = VectorStore()


# ============================================================
# 找到新闻对应的事件
# ============================================================

def find_event_by_news(news_id):

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT event_id
        FROM event_news
        WHERE news_id = ?
        """,
        (news_id,)
    )

    row = cursor.fetchone()

    conn.close()

    if row:
        return row[0]

    return None


# ============================================================
# 获取事件代表新闻
# ============================================================

def get_event_news(event_id):

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT news_id
        FROM event_news
        WHERE event_id = ?
        """,
        (event_id,)
    )

    rows = cursor.fetchall()

    conn.close()

    return [
        row[0]
        for row in rows
    ]


# ============================================================
# 更新事件统计
# ============================================================

def update_event(event_id):

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            COUNT(*),
            MIN(n.published),
            MAX(n.published),
            MAX(n.importance)
        FROM event_news en
        JOIN news n
            ON en.news_id = n.id
        WHERE en.event_id = ?
        """,
        (event_id,)
    )

    count, first_date, last_date, importance = (
        cursor.fetchone()
    )

    cursor.execute(
        """
        UPDATE events
        SET
            news_count = ?,
            first_published = ?,
            last_published = ?,
            importance = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            count,
            first_date,
            last_date,
            importance or 0,
            event_id
        )
    )

    conn.commit()

    conn.close()


# ============================================================
# 加入已有事件
# ============================================================

def add_news_to_event(
    event_id,
    news_id,
    similarity
):

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR IGNORE INTO event_news (
            event_id,
            news_id,
            similarity
        )
        VALUES (?, ?, ?)
        """,
        (
            event_id,
            news_id,
            similarity
        )
    )

    conn.commit()

    conn.close()

    update_event(event_id)


# ============================================================
# 创建新事件
# ============================================================

def create_new_event(news_id):

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            title,
            summary,
            llm_category,
            keywords,
            importance,
            published
        FROM news
        WHERE id = ?
        """,
        (news_id,)
    )

    row = cursor.fetchone()

    if not row:

        conn.close()

        return None

    title = row[0] or "未命名事件"

    summary = row[1] or ""

    category = row[2] or ""

    keywords = row[3] or ""

    importance = row[4] or 0

    published = row[5]

    # 创建事件
    cursor.execute(
        """
        INSERT INTO events (
            event_name,
            summary,
            category,
            keywords,
            importance,
            news_count,
            first_published,
            last_published
        )
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            title,
            summary,
            category,
            keywords,
            importance,
            published,
            published
        )
    )

    event_id = cursor.lastrowid

    # 建立关系
    cursor.execute(
        """
        INSERT INTO event_news (
            event_id,
            news_id,
            similarity,
            is_representative
        )
        VALUES (?, ?, ?, 1)
        """,
        (
            event_id,
            news_id,
            1.0
        )
    )

    conn.commit()

    conn.close()

    return event_id


# ============================================================
# 处理一条新新闻
# ============================================================

def process_news(news_id):

    # --------------------------------------------------------
    # 已经属于事件
    # --------------------------------------------------------

    existing_event = find_event_by_news(
        news_id
    )

    if existing_event:

        return existing_event

    # --------------------------------------------------------
    # 从 Chroma 找相似新闻
    # --------------------------------------------------------

    result = vector_store.collection.get(
        ids=[str(news_id)],
        include=["embeddings"]
    )

    embeddings = result["embeddings"]

    if not embeddings:

        print(
            f"news_id={news_id} 没有Embedding"
        )

        return None

    embedding = embeddings[0]

    search_result = (
        vector_store.collection.query(
            query_embeddings=[embedding],
            n_results=10
        )
    )

    similar_ids = (
        search_result["ids"][0]
    )

    distances = (
        search_result["distances"][0]
    )

    # --------------------------------------------------------
    # 找相似新闻对应的事件
    # --------------------------------------------------------

    event_candidates = []

    for similar_id, distance in zip(
        similar_ids,
        distances
    ):

        similar_news_id = int(
            similar_id
        )

        # 自己跳过
        if similar_news_id == news_id:
            continue

        similarity = 1 - distance

        if similarity < EVENT_THRESHOLD:
            continue

        event_id = find_event_by_news(
            similar_news_id
        )

        if event_id:

            event_candidates.append(
                (
                    event_id,
                    similarity
                )
            )

    # --------------------------------------------------------
    # 找到已有事件
    # --------------------------------------------------------

    if event_candidates:

        event_id, similarity = max(
            event_candidates,
            key=lambda x: x[1]
        )

        add_news_to_event(
            event_id,
            news_id,
            similarity
        )

        print(
            f"news_id={news_id}"
            f" → Event {event_id}"
            f" similarity={similarity:.3f}"
        )

        return event_id

    # --------------------------------------------------------
    # 没有匹配事件
    # --------------------------------------------------------

    event_id = create_new_event(
        news_id
    )

    print(
        f"news_id={news_id}"
        f" → 创建新事件 Event {event_id}"
    )

    return event_id


# ============================================================
# 处理所有 analyzed / embedded 新闻
# ============================================================

def main():

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM news
        WHERE status = 'embedded'
        ORDER BY id
        """
    )

    news_ids = [
        row[0]
        for row in cursor.fetchall()
    ]

    conn.close()

    print(
        f"待匹配事件新闻：{len(news_ids)}"
    )

    for news_id in news_ids:

        try:

            process_news(
                news_id
            )

        except Exception as e:

            print(
                f"[失败] news_id={news_id}: {e}"
            )


if __name__ == "__main__":

    main()