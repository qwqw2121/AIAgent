# storage/db.py
import json
import os
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(os.getenv("NEWS_DB_PATH", Path(__file__).parent / "news.db"))

import json
import time
from collections import Counter

DONE_STATUSES = ("analyzed", "embedded", "embed_failed", "clustered", "reported")

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

import time

DONE_STATUSES = ("analyzed", "embedded", "embed_failed", "clustered", "reported")

def fetch_important_recent(limit=8, min_importance=7, hours=24):
    since = int(time.time()) - hours * 3600
    ph = ",".join("?" * len(DONE_STATUSES))
    conn = get_connection()
    try:
        rows = conn.execute(f"""
            SELECT id, title, source, published, summary,
                   llm_category, importance, url
            FROM news
            WHERE is_duplicate = 0
              AND importance >= ?
              AND status IN ({ph})
              AND published_ts >= ?
            ORDER BY importance DESC, published_ts DESC
            LIMIT ?
        """, (min_importance, *DONE_STATUSES, since, limit)).fetchall()
    finally:
        conn.close()
    keys = ["id", "title", "source", "published", "summary",
            "llm_category", "importance", "url"]
    return [dict(zip(keys, r)) for r in rows]


import json
import time
from collections import Counter

DONE_STATUSES = ("analyzed", "embedded", "embed_failed", "clustered", "reported")


def fetch_trends(days: int = 30) -> dict:
    """过去 N 天趋势总览：统计数字、热门技术、每日数量、重要事件"""
    ph = ",".join("?" * len(DONE_STATUSES))
    since = f"-{days} days"
    conn = get_connection()
    try:
        # 1. 核心统计
        row = conn.execute(
            f"""SELECT COUNT(*),
                       SUM(CASE WHEN importance >= 7 THEN 1 ELSE 0 END),
                       COUNT(DISTINCT llm_category)
                FROM news
                WHERE is_duplicate = 0 AND status IN ({ph})
                  AND published >= date('now', ?)""",
            (*DONE_STATUSES, since),
        ).fetchone()
        total_news = row[0] or 0
        important_news = row[1] or 0
        hot_directions = row[2] or 0

        # 2. 每日数量（按日期分组，不是按完整时间戳）
        daily_counts = [
            {"date": r[0], "count": r[1]}
            for r in conn.execute(
                f"""SELECT substr(published, 1, 10) AS d, COUNT(*)
                    FROM news
                    WHERE is_duplicate = 0 AND status IN ({ph})
                      AND published >= date('now', ?)
                    GROUP BY d ORDER BY d""",
                (*DONE_STATUSES, since),
            ).fetchall()
        ]

        # 3. 热门技术：keywords 是 JSON 字符串，统计词频
        counter: Counter = Counter()
        for (kw_json,) in conn.execute(
            f"""SELECT keywords FROM news
                WHERE is_duplicate = 0 AND status IN ({ph})
                  AND published >= date('now', ?)""",
            (*DONE_STATUSES, since),
        ).fetchall():
            try:
                kws = json.loads(kw_json) if kw_json else []
                if isinstance(kws, list):
                    counter.update(k for k in kws if isinstance(k, str) and k.strip())
            except (json.JSONDecodeError, TypeError):
                continue
        hot_tech = [{"name": k, "count": v} for k, v in counter.most_common(8)]

        # 4. 重要事件：最近 7 份日报里的事件，取前 10 个
        events = []
        for (report_json,) in conn.execute(
            "SELECT report_json FROM daily_reports ORDER BY report_date DESC LIMIT 7"
        ).fetchall():
            try:
                for ev in (json.loads(report_json).get("events") or []):
                    events.append({"rank": len(events) + 1, "title": ev.get("title", "")})
                    if len(events) >= 10:
                        break
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
            if len(events) >= 10:
                break

        # 5. 主要事件数（去重后的标题数）
        main_events = len({e["title"] for e in events})

        return {
            "days": days,
            "total_news": total_news,
            "important_news": important_news,
            "main_events": main_events,
            "hot_directions": hot_directions,
            "hot_tech": hot_tech,
            "daily_counts": daily_counts,
            "events": events,
        }
    finally:
        conn.close()