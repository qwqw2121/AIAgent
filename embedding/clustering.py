"""
④ 事件聚类

作用：
    Chroma 中的大量新闻向量
            ↓
        DBSCAN 聚类
            ↓
        自动形成事件簇
            ↓
        写入 SQLite
        ├── events
        └── event_news

注意：
    本脚本主要用于“第一次建立历史事件库”。

    后续新增 RSS 新闻：
        不要重新运行本脚本
        使用 incremental_event.py
"""

import json
import sqlite3
from pathlib import Path

import numpy as np
from sklearn.cluster import DBSCAN

from vector_store import VectorStore


# ============================================================
# 配置
# ============================================================

DB_PATH = (
    Path(__file__).parent.parent
    / "storage"
    / "news.db"
)

vector_store = VectorStore()


# cosine distance
#
# cosine similarity = 1 - cosine distance
#
# 例如：
#
# similarity = 0.90
# distance   = 0.10
#
# similarity = 0.80
# distance   = 0.20
#
# 这里先使用 0.10
#
# 后面需要根据你的实际新闻数据调整。
#
EPS = 0.10

MIN_SAMPLES = 2


# ============================================================
# ① 初始化事件表
# ============================================================

def init_event_tables():

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    # --------------------------------------------------------
    # events
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            event_name TEXT NOT NULL,

            summary TEXT,

            category TEXT,

            keywords TEXT,

            importance REAL DEFAULT 0,

            news_count INTEGER DEFAULT 0,

            first_published TEXT,

            last_published TEXT,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------------------------------------------
    # event_news
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_news (

            event_id INTEGER NOT NULL,

            news_id INTEGER NOT NULL,

            similarity REAL,

            is_representative INTEGER DEFAULT 0,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            PRIMARY KEY (event_id, news_id),

            FOREIGN KEY (event_id)
                REFERENCES events(id),

            FOREIGN KEY (news_id)
                REFERENCES news(id)
        )
    """)

    # --------------------------------------------------------
    # 索引
    # --------------------------------------------------------

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_event_news_event
        ON event_news(event_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_event_news_news
        ON event_news(news_id)
    """)

    conn.commit()
    conn.close()

    print("✅ events / event_news 表已准备")


# ============================================================
# ② 获取 Chroma 中所有新闻向量
# ============================================================

def load_embeddings():

    result = vector_store.get_all()

    ids = result["ids"]

    embeddings = result["embeddings"]

    metadatas = result["metadatas"]

    if embeddings is None:

        return (
            ids,
            np.array([]),
            metadatas,
        )

    return (
        ids,
        np.array(embeddings),
        metadatas,
    )


# ============================================================
# ③ DBSCAN 聚类
# ============================================================

def cluster_news():

    ids, embeddings, metadatas = (
        load_embeddings()
    )

    if len(embeddings) == 0:

        print("❌ 向量数据库为空")

        return {}

    print(
        f"Chroma 新闻数量：{len(embeddings)}"
    )

    print(
        "🔄 开始 DBSCAN 聚类..."
    )

    clustering = DBSCAN(
        eps=EPS,
        min_samples=MIN_SAMPLES,
        metric="cosine",
    )

    labels = clustering.fit_predict(
        embeddings
    )

    # --------------------------------------------------------
    # 整理 Cluster
    # --------------------------------------------------------

    clusters = {}

    noise_count = 0

    for news_id, label, metadata in zip(
        ids,
        labels,
        metadatas,
    ):

        # -1 = 噪声
        if label == -1:

            noise_count += 1

            continue

        if label not in clusters:

            clusters[label] = []

        clusters[label].append({

            "news_id": int(news_id),

            "title": metadata.get(
                "title",
                ""
            ),

            "source": metadata.get(
                "source",
                ""
            ),

            "category": metadata.get(
                "category",
                ""
            ),

        })

    print(
        f"✅ DBSCAN 完成"
    )

    print(
        f"事件簇数量：{len(clusters)}"
    )

    print(
        f"噪声新闻数量：{noise_count}"
    )

    return clusters


# ============================================================
# ④ 从 SQLite 获取新闻详细信息
# ============================================================

def get_news(news_ids):

    if not news_ids:

        return {}

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    placeholders = ",".join(
        "?" for _ in news_ids
    )

    cursor.execute(
        f"""
        SELECT *
        FROM news
        WHERE id IN ({placeholders})
        """,
        news_ids,
    )

    rows = cursor.fetchall()

    conn.close()

    return {
        row["id"]: row
        for row in rows
    }


# ============================================================
# ⑤ 选择事件代表新闻
# ============================================================

def choose_representative(
    news_rows
):

    if not news_rows:

        return None

    # 优先选择 importance 高的新闻
    #
    # 如果 importance 一样，
    # 就选择第一篇。

    return max(
        news_rows,
        key=lambda row: (
            row["importance"]
            or 0
        )
    )


# ============================================================
# ⑥ 创建事件
# ============================================================

def create_event(
    news_rows
):

    if not news_rows:

        return None

    representative = (
        choose_representative(
            news_rows
        )
    )

    # --------------------------------------------------------
    # 事件名称
    #
    # 第一版直接使用代表新闻标题。
    #
    # 后面可以再让 LLM 根据整个 Cluster
    # 自动生成更加抽象的事件名称。
    # --------------------------------------------------------

    event_name = (
        representative["title"]
        or "未命名事件"
    )

    summary = (
        representative["summary"]
        or ""
    )

    category = (
        representative["llm_category"]
        or ""
    )

    importance = (
        representative["importance"]
        or 0
    )

    # --------------------------------------------------------
    # 汇总关键词
    # --------------------------------------------------------

    keywords_set = set()

    for row in news_rows:

        raw_keywords = (
            row["keywords"]
            or ""
        )

        if not raw_keywords:

            continue

        try:

            keywords = json.loads(
                raw_keywords
            )

            if isinstance(
                keywords,
                list
            ):

                for keyword in keywords:

                    keywords_set.add(
                        str(keyword)
                    )

        except Exception:

            pass

    keywords_json = json.dumps(
        list(keywords_set),
        ensure_ascii=False
    )

    # --------------------------------------------------------
    # 时间
    # --------------------------------------------------------

    published_dates = [

        row["published"]

        for row in news_rows

        if row["published"]
    ]

    if published_dates:

        first_published = min(
            published_dates
        )

        last_published = max(
            published_dates
        )

    else:

        first_published = None
        last_published = None

    # --------------------------------------------------------
    # 写入 events
    # --------------------------------------------------------

    conn = sqlite3.connect(
        DB_PATH
    )

    cursor = conn.cursor()

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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_name,
            summary,
            category,
            keywords_json,
            importance,
            len(news_rows),
            first_published,
            last_published,
        ),
    )

    event_id = cursor.lastrowid

    # --------------------------------------------------------
    # 写入 event_news
    # --------------------------------------------------------

    for row in news_rows:

        is_representative = (
            1
            if row["id"]
            == representative["id"]
            else 0
        )

        cursor.execute(
            """
            INSERT OR IGNORE INTO event_news (
                event_id,
                news_id,
                similarity,
                is_representative
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                event_id,
                row["id"],
                None,
                is_representative,
            ),
        )

    conn.commit()
    conn.close()

    return event_id


# ============================================================
# ⑦ 将所有 Cluster 写入 SQLite
# ============================================================

def save_clusters(
    clusters
):

    if not clusters:

        print(
            "没有可以写入的事件簇"
        )

        return

    # --------------------------------------------------------
    # 所有新闻 ID
    # --------------------------------------------------------

    all_news_ids = []

    for news_list in clusters.values():

        for news in news_list:

            all_news_ids.append(
                news["news_id"]
            )

    # --------------------------------------------------------
    # 获取完整新闻数据
    # --------------------------------------------------------

    news_dict = get_news(
        all_news_ids
    )

    print()
    print(
        "🔄 开始写入 SQLite..."
    )

    event_count = 0

    # --------------------------------------------------------
    # 一个 Cluster = 一个 Event
    # --------------------------------------------------------

    for cluster_id, news_list in (
        clusters.items()
    ):

        cluster_news = []

        for news in news_list:

            news_id = news[
                "news_id"
            ]

            row = news_dict.get(
                news_id
            )

            if row:

                cluster_news.append(
                    row
                )

        if not cluster_news:

            continue

        event_id = create_event(
            cluster_news
        )

        event_count += 1

        print(
            f"[Cluster {cluster_id}] "
            f"→ Event {event_id} "
            f"→ {len(cluster_news)} 条新闻"
        )

    print()
    print(
        f"✅ 成功创建 {event_count} 个事件"
    )


# ============================================================
# ⑧ 打印事件簇
# ============================================================

def print_clusters(
    clusters
):

    print()
    print(
        "=" * 70
    )

    print(
        "事件聚类结果"
    )

    print(
        "=" * 70
    )

    for cluster_id, news_list in (
        clusters.items()
    ):

        print()

        print(
            f"========== "
            f"Cluster {cluster_id} "
            f"({len(news_list)} 条) "
            f"=========="
        )

        for news in news_list:

            print(
                f"{news['news_id']} | "
                f"{news['title']}"
            )


# ============================================================
# 主程序
# ============================================================

def main():

    print(
        "=" * 70
    )

    print(
        "AI News Event Clustering"
    )

    print(
        "=" * 70
    )

    # --------------------------------------------------------
    # 初始化表
    # --------------------------------------------------------

    init_event_tables()

    # --------------------------------------------------------
    # 聚类
    # --------------------------------------------------------

    clusters = cluster_news()

    if not clusters:

        return

    # --------------------------------------------------------
    # 打印
    # --------------------------------------------------------

    print_clusters(
        clusters
    )

    # --------------------------------------------------------
    # 写入数据库
    # --------------------------------------------------------

    save_clusters(
        clusters
    )

    print()
    print(
        "🎉 事件聚类全部完成"
    )


# ============================================================

if __name__ == "__main__":

    main()