# storage/db.py
import json
import os
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(os.getenv("NEWS_DB_PATH", Path(__file__).parent / "news.db"))

_init_lock = threading.Lock()
_initialized = False

# ============================================================
# 表结构（全项目唯一的建表入口）
# ============================================================
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
]


# ============================================================
# 连接
# ============================================================
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
        for name, ddl in _MIGRATIONS:
            if name not in cols:
                conn.execute(f"ALTER TABLE news ADD COLUMN {name} {ddl}")
        for ddl in _INDEXES:
            conn.execute(ddl)
        conn.commit()
    finally:
        conn.close()


def get_connection(row_factory=True):
    """
    全项目唯一的取连接入口。
    默认返回 sqlite3.Row：既能 row["title"]，也能 row[0]、dict(zip(cols, row))，
    所以对 pipeline 里的旧写法和后端 API 都兼容。
    每个线程/函数自己取、自己关，不要跨线程共享。
    """
    global _initialized
    if not _initialized:
        with _init_lock:
            if not _initialized:
                init_db()
                _initialized = True
    return _connect(row_factory)


# ============================================================
# 内部工具：不依赖 row_factory，统一转 dict
# ============================================================
def _all_dicts(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _one_dict(cur):
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip([c[0] for c in cur.description], row))


# ============================================================
# 新闻：流水线用
# ============================================================
def update_fields(conn, news_id, fields, commit=True):
    if not fields:
        return False
    fields = dict(fields)
    if isinstance(fields.get("keywords"), list):
        fields["keywords"] = json.dumps(fields["keywords"], ensure_ascii=False)
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE news SET {set_clause} WHERE id = ?",
        [*fields.values(), news_id],
    )
    if commit:
        conn.commit()
    return True


def fetch_by_status(conn, status, limit=None):
    """status 可传字符串或元组"""
    statuses = (status,) if isinstance(status, str) else tuple(status)
    marks = ",".join("?" * len(statuses))
    sql = (f"SELECT * FROM news WHERE status IN ({marks}) "
           f"AND is_duplicate = 0 ORDER BY id")
    params = list(statuses)
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return _all_dicts(conn.execute(sql, params))


# ============================================================
# 新闻：后端 API 用
# ============================================================
def query_news(conn, category=None, keyword=None, min_importance=None, limit=20,
               status=("analyzed", "embedded", "clustered", "reported")):
    statuses = (status,) if isinstance(status, str) else tuple(status)
    marks = ",".join("?" * len(statuses))
    sql = f"""
        SELECT id, title, source, published, published_ts, summary,
               llm_category, keywords, importance, url, status
        FROM news
        WHERE is_duplicate = 0 AND status IN ({marks})
    """
    params = list(statuses)
    if category:
        sql += " AND llm_category = ?"
        params.append(category)
    if keyword:
        sql += """ AND (title LIKE ? COLLATE NOCASE
                     OR summary LIKE ? COLLATE NOCASE
                     OR keywords LIKE ? COLLATE NOCASE)"""
        params += [f"%{keyword}%"] * 3
    if min_importance is not None:
        sql += " AND importance >= ?"
        params.append(min_importance)
    sql += " ORDER BY published_ts DESC LIMIT ?"
    params.append(limit)
    return _all_dicts(conn.execute(sql, params))


def fetch_news_by_ids(conn, news_ids):
    """按 id 批量取新闻（日报 enrich 使用），返回 {id: dict}"""
    news_ids = list(news_ids or [])
    if not news_ids:
        return {}
    marks = ",".join("?" * len(news_ids))
    cur = conn.execute(
        f"""SELECT id, title, source, published, summary, content,
                   llm_category, keywords, importance, url
            FROM news WHERE id IN ({marks})""",
        news_ids,
    )
    return {d["id"]: d for d in _all_dicts(cur)}


# ============================================================
# 日报
# ============================================================
def fetch_report_by_date(conn, report_date: str):
    cur = conn.execute(
        "SELECT report_date, overview, report_json "
        "FROM daily_reports WHERE report_date = ?",
        (report_date,),
    )
    return _one_dict(cur)


def fetch_reports_range(conn, start_date: str, end_date: str):
    cur = conn.execute(
        "SELECT report_date, overview, report_json "
        "FROM daily_reports WHERE report_date >= ? AND report_date <= ? "
        "ORDER BY report_date DESC",
        (start_date, end_date),
    )
    return _all_dicts(cur)


def report_exists(conn, report_date: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM daily_reports WHERE report_date = ?", (report_date,)
    ).fetchone() is not None


# ============================================================
# 元信息
# ============================================================
def table_columns(conn, table_name: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def table_exists(conn, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone() is not None