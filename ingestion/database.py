#负责SQLite操作。

import sqlite3
from pathlib import Path


DB_PATH = Path("storage/news.db")


def get_connection():

    DB_PATH.parent.mkdir(
        exist_ok=True
    )

    conn = sqlite3.connect(
        DB_PATH
    )

    return conn



def init_db():

    conn = get_connection()

    cursor = conn.cursor()


    cursor.execute("""
    CREATE TABLE IF NOT EXISTS news(

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        title TEXT,

        url TEXT UNIQUE,

        source TEXT,

        language TEXT,

        rss_summary TEXT,

        content TEXT,

        llm_summary TEXT,

        keywords TEXT,

        category TEXT,

        importance INTEGER,

        publish_time TEXT,

        created_time TEXT,

        embedding_status INTEGER DEFAULT 0

    )
    """)


    conn.commit()

    conn.close()



def insert_news(news):

    conn=get_connection()

    cursor=conn.cursor()


    cursor.execute("""

    INSERT OR IGNORE INTO news(

        title,
        url,
        source,
        language,
        rss_summary,
        publish_time

    )

    VALUES(?,?,?,?,?,?)

    """,
    (

        news["title"],
        news["url"],
        news["source"],
        news["language"],
        news["summary"],
        news["published"]

    ))


    conn.commit()

    conn.close()



if __name__=="__main__":

    init_db()