# embedding/event_store.py


import sqlite3
from pathlib import Path


# DB_PATH = (
#     Path(__file__).parent.parent
#     / "storage"
#     / "news.db"
# )
import os
DB_PATH = os.getenv("NEWS_DB_PATH", Path(__file__).parent.parent / "storage/news.db")

def init_event_tables():

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    # ========================================================
    # 事件表
    # ========================================================

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

    # ========================================================
    # 新闻-事件关系表
    # ========================================================

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

    # ========================================================
    # 索引
    # ========================================================

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

    print("✅ events / event_news 表创建完成")


if __name__ == "__main__":

    init_event_tables()