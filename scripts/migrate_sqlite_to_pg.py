# scripts/migrate_sqlite_to_pg.py
import sqlite3, psycopg2, os

sqlite_conn = sqlite3.connect("storage/news.db")
sqlite_conn.row_factory = sqlite3.Row
pg_conn = psycopg2.connect(os.getenv("PG_DSN"))  # postgresql://news:news_pwd@localhost:5432/news_db

rows = sqlite_conn.execute("SELECT * FROM news").fetchall()
cols = rows[0].keys() if rows else []

with pg_conn.cursor() as cur:
    for r in rows:
        d = dict(r)
        d.pop("id", None)  # 用 postgres 自增
        placeholders = ", ".join(["%s"] * len(d))
        col_str = ", ".join(d.keys())
        cur.execute(
            f"INSERT INTO news ({col_str}) VALUES ({placeholders}) ON CONFLICT (url) DO NOTHING",
            list(d.values()),
        )
pg_conn.commit()
print(f"迁移完成，共 {len(rows)} 条")