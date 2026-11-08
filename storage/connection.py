# storage/connection.py
"""连接、建表、迁移、通用 row 工具。全项目唯一的建表/取连接入口。"""
import os
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(os.getenv("NEWS_DB_PATH", Path(__file__).parent / "news.db"))

DONE_STATUSES = ("analyzed", "embedded", "embed_failed", "clustered", "reported")

# 读取摘要时优先用 LLM 摘要，没有则回退到原始摘要；
# 别名仍叫 summary，所以前端 / 日报 / API 读到的字段名不变，无需改动
SUMMARY_EXPR = "COALESCE(NULLIF(llm_summary, ''), summary) AS summary"

_init_lock = threading.Lock()
_initialized = False

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        title_hash TEXT,
        source TEXT,
        language TEXT,
        category TEXT,
        published TEXT,
        published_ts INTEGER,
        crawl_time TEXT,
        content TEXT,
        summary TEXT,
        llm_summary TEXT,
        llm_category TEXT,
        keywords TEXT,
        importance INTEGER,
        status TEXT DEFAULT 'raw',
        is_duplicate INTEGER DEFAULT 0,
        duplicate_of INTEGER,
        extract_status TEXT,
        extract_attempts INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_date TEXT UNIQUE NOT NULL,
        overview TEXT,
        report_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # 以下两张表按 incremental_event.py 的 INSERT 推断，请和现有库对一下
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_name TEXT,
        summary TEXT,
        category TEXT,
        keywords TEXT,
        importance INTEGER DEFAULT 0,
        news_count INTEGER DEFAULT 0,
        first_published TEXT,
        last_published TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS event_news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        news_id INTEGER NOT NULL UNIQUE,
        similarity REAL,
        is_representative INTEGER DEFAULT 0
    )
    """,
]

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_status ON news(status)",
    "CREATE INDEX IF NOT EXISTS idx_published_ts ON news(published_ts)",
    "CREATE INDEX IF NOT EXISTS idx_daily_reports_date ON daily_reports(report_date)",
    "CREATE INDEX IF NOT EXISTS idx_event_news_event ON event_news(event_id)",
]

# 老库缺的列：(列名, 类型定义)
_MIGRATIONS = [
    ("is_duplicate", "INTEGER DEFAULT 0"),
    ("duplicate_of", "INTEGER"),
    ("extract_status", "TEXT"),
    ("extract_attempts", "INTEGER DEFAULT 0"),
    ("llm_summary", "TEXT"),
    ("embed_attempts", "INTEGER DEFAULT 0"),
]


def _connect(row_factory=True):
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False,   # FastAPI 依赖和 endpoint 可能在不同线程
    )
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    if row_factory:
        conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建表 + 补列 + 建索引，幂等，可重复调用"""
    conn = _connect()
    try:
        for ddl in _SCHEMA:
            conn.execute(ddl)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(news)")}
        added = set()
        for name, ddl in _MIGRATIONS:
            if name not in cols:
                conn.execute(f"ALTER TABLE news ADD COLUMN {name} {ddl}")
                added.add(name)

        # 一次性回填：旧版本把 LLM 摘要直接写进了 summary，
        # 新增 llm_summary 列时，把已分析记录的 summary 复制过去，保证老数据不丢
        if "llm_summary" in added:
            marks = ",".join("?" * len(DONE_STATUSES))
            conn.execute(
                f"""UPDATE news SET llm_summary = summary
                    WHERE llm_summary IS NULL AND status IN ({marks})""",
                DONE_STATUSES,
            )

        for ddl in _INDEXES:
            conn.execute(ddl)
        conn.commit()
    finally:
        conn.close()


def get_connection(row_factory=True):
    """
    全项目唯一的取连接入口。
    默认返回 sqlite3.Row：既能 row["title"]，也能 row[0]、dict(zip(cols, row))。
    每个线程/函数自己取、自己关，不要跨线程共享。
    """
    global _initialized
    if not _initialized:
        with _init_lock:
            if not _initialized:
                init_db()
                _initialized = True
    return _connect(row_factory)


# ---------- 不依赖 row_factory，统一转 dict ----------
def all_dicts(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def one_dict(cur):
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip([c[0] for c in cur.description], row))


# ---------- 元信息 ----------
def table_columns(conn, table_name: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def table_exists(conn, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone() is not None