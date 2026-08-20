import sqlite3
from pathlib import Path


DB_PATH = Path("storage/news.db")


def init_db():
    # 确保 storage 目录存在
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 开启外键约束
    cursor.execute("PRAGMA foreign_keys = ON")
    
    # ---------- 每日新闻总结 ----------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_date TEXT UNIQUE NOT NULL,
        overview TEXT,
        report_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

    # # ============================================================
    # # 1. 新闻主表 news
    # # ============================================================

    # # 你的 news 表已经存在，所以这里只负责补充缺失字段
    # existing_columns = {
    #     row[1]
    #     for row in cursor.execute("PRAGMA table_info(news)").fetchall()
    # }

    # new_columns = {
    #     "extract_status": "TEXT DEFAULT 'pending'",
    #     "author": "TEXT",
    #     "content_hash": "TEXT",
    #     "duplicate_of": "INTEGER",
    #     "cluster_id": "INTEGER",
    #     "embedding_status": "TEXT DEFAULT 'pending'",
    #     "embedding_model": "TEXT",
    # }

    # for column_name, column_type in new_columns.items():
    #     if column_name not in existing_columns:
    #         cursor.execute(
    #             f"ALTER TABLE news ADD COLUMN {column_name} {column_type}"
    #         )

    # ============================================================
    # 2. RSS / 新闻来源表
    # ============================================================

    # cursor.execute("""
    # CREATE TABLE IF NOT EXISTS news_sources (
    #     id INTEGER PRIMARY KEY AUTOINCREMENT,
    #     name TEXT NOT NULL,
    #     url TEXT UNIQUE NOT NULL,
    #     source_type TEXT DEFAULT 'rss',
    #     language TEXT,
    #     category TEXT,
    #     enabled INTEGER DEFAULT 1,
    #     crawl_interval INTEGER DEFAULT 3600,
    #     last_crawl_time TEXT,
    #     created_at TEXT DEFAULT CURRENT_TIMESTAMP
    # )
    # """)

    # ============================================================
    # 3. 采集日志表 crawl_logs
    # ============================================================

    # cursor.execute("""
    # CREATE TABLE IF NOT EXISTS crawl_logs (
    #     id INTEGER PRIMARY KEY AUTOINCREMENT,
    #     task_id TEXT UNIQUE,
    #     source_name TEXT,
    #     status TEXT DEFAULT 'running',
    #     total_count INTEGER DEFAULT 0,
    #     inserted_count INTEGER DEFAULT 0,
    #     skipped_count INTEGER DEFAULT 0,
    #     error_message TEXT,
    #     start_time TEXT,
    #     end_time TEXT,
    #     created_at TEXT DEFAULT CURRENT_TIMESTAMP
    # )
    # """)

    # ============================================================
    # 4. 新闻 Embedding 信息表
    # ============================================================
    #
    # 注意：
    # 如果以后使用 Chroma / Qdrant / Milvus，
    # 真正的向量建议放在向量数据库里。
    #
    # SQLite 这里只保存：
    # news_id -> vector_id -> model_name
    #
    # 不再保存 embedding BLOB。
    #

    # cursor.execute("""
    # CREATE TABLE IF NOT EXISTS news_embeddings (
    #     id INTEGER PRIMARY KEY AUTOINCREMENT,
    #     news_id INTEGER UNIQUE NOT NULL,
    #     vector_id TEXT UNIQUE NOT NULL,
    #     model_name TEXT NOT NULL,
    #     vector_db TEXT DEFAULT 'chroma',
    #     created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    #     FOREIGN KEY (news_id)
    #         REFERENCES news(id)
    #         ON DELETE CASCADE
    # )
    # """)

    # ============================================================
    # 5. 新闻聚类表 news_clusters
    # ============================================================

    # cursor.execute("""
    # CREATE TABLE IF NOT EXISTS news_clusters (
    #     id INTEGER PRIMARY KEY AUTOINCREMENT,
    #     name TEXT,
    #     description TEXT,
    #     category TEXT,
    #     keywords TEXT,
    #     news_count INTEGER DEFAULT 0,
    #     created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    #     updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    # )
    # """)

    # # ============================================================
    # # 6. 每日报告表 daily_reports
    # # ============================================================

    # cursor.execute("""
    # CREATE TABLE IF NOT EXISTS daily_reports (
    #     id INTEGER PRIMARY KEY AUTOINCREMENT,
    #     report_date TEXT UNIQUE NOT NULL,
    #     title TEXT,
    #     content TEXT,
    #     summary TEXT,
    #     news_ids TEXT,
    #     word_count INTEGER,
    #     status TEXT DEFAULT 'draft',
    #     published_at TEXT,
    #     created_at TEXT DEFAULT CURRENT_TIMESTAMP
    # )
    # """)

    # ============================================================
    # 7. 索引
    # ============================================================

    # # news
    # cursor.execute("""
    # CREATE INDEX IF NOT EXISTS idx_news_status
    # ON news(status)
    # """)

    # cursor.execute("""
    # CREATE INDEX IF NOT EXISTS idx_news_published
    # ON news(published_ts)
    # """)

    # cursor.execute("""
    # CREATE INDEX IF NOT EXISTS idx_news_content_hash
    # ON news(content_hash)
    # """)

    # cursor.execute("""
    # CREATE INDEX IF NOT EXISTS idx_news_title_hash
    # ON news(title_hash)
    # """)

    # cursor.execute("""
    # CREATE INDEX IF NOT EXISTS idx_news_duplicate
    # ON news(is_duplicate)
    # """)

    # cursor.execute("""
    # CREATE INDEX IF NOT EXISTS idx_news_cluster
    # ON news(cluster_id)
    # """)

    # cursor.execute("""
    # CREATE INDEX IF NOT EXISTS idx_news_embedding_status
    # ON news(embedding_status)
    # """)

    # news_embeddings
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_news_embeddings_news
    ON news_embeddings(news_id)
    """)

    # # crawl_logs
    # cursor.execute("""
    # CREATE INDEX IF NOT EXISTS idx_crawl_logs_status
    # ON crawl_logs(status)
    # """)

    # ============================================================
    # 8. 提交
    # ============================================================

    conn.commit()
    conn.close()

    print("✅ 数据库初始化完成")


if __name__ == "__main__":
    init_db()