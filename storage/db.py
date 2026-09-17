import os
import sqlite3
import json
from pathlib import Path

# SQLite 数据库文件路径，默认放在 storage 目录下
DB_PATH = os.getenv("NEWS_DB_PATH", Path(__file__).parent.parent / "storage/news.db")

def get_connection():
    """获取 SQLite 数据库连接"""
    # 确保存放数据库文件的目录存在
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    # 关键：设置 row_factory 为 sqlite3.Row，使得查询结果可以像字典一样通过列名访问
    conn.row_factory = sqlite3.Row
    # 开启外键约束（好习惯）
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    """初始化：建索引（幂等，可重复调用）"""
    with get_connection() as conn:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_reports_date "
            "ON daily_reports(report_date)"
        )

def fetch_by_status(conn, status, limit=None):
    """根据状态获取新闻"""
    statuses = [status] if isinstance(status, str) else list(status)

    # SQLite 不支持 ANY(%s)，需要动态生成 IN (?, ?, ?) 的占位符
    placeholders = ", ".join("?" for _ in statuses)

    sql = f"""
        SELECT id, url, title, content, summary, source,
               published, published_ts, crawl_time, status
        FROM news
        WHERE status IN ({placeholders}) AND is_duplicate = 0
        ORDER BY published_ts DESC
    """
    params = list(statuses)
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    # 使用 with conn: 可以在代码块结束时自动 commit，发生异常时自动 rollback
    with conn:
        cur = conn.execute(sql, params)
        # 将 sqlite3.Row 对象转换为普通的 dict，保持与原 psycopg 代码 100% 兼容
        return [dict(row) for row in cur.fetchall()]

def update_fields(conn, news_id, fields: dict):
    """更新指定 news_id 的字段"""
    # 过滤掉 None 值，保持数据干净
    clean_fields = {k: v for k, v in fields.items() if v is not None}

    if "keywords" in clean_fields and isinstance(clean_fields["keywords"], list):
        clean_fields["keywords"] = json.dumps(clean_fields["keywords"], ensure_ascii=False)

    set_clause = ", ".join(f"{k} = ?" for k in clean_fields)
    values = list(clean_fields.values()) + [news_id]

    sql = f"UPDATE news SET {set_clause} WHERE id = ?"
    with conn:
        conn.execute(sql, values)


def query_news(conn, category=None, keyword=None, min_importance=None, limit=20,
               status=("embedded",)):                 # ← 默认参数
    statuses = [status] if isinstance(status, str) else list(status)
    placeholders = ", ".join("?" for _ in statuses)

    sql = f"""
        SELECT ...
        FROM news
        WHERE is_duplicate = 0 AND status IN ({placeholders})   # ← 动态
    """
    params = list(statuses)
    if category:
        sql += " AND llm_category = ?"
        params.append(category)

    if keyword:
        sql += """ AND (
            title    LIKE ? COLLATE NOCASE
            OR summary LIKE ? COLLATE NOCASE
            OR keywords LIKE ? COLLATE NOCASE
        )"""
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])

    if min_importance is not None:
        sql += " AND importance >= ?"
        params.append(min_importance)

    sql += " ORDER BY published_ts DESC LIMIT ?"
    params.append(limit)

    with conn:
        cur = conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

# ============ 日报相关查询（backend/main.py 统一走这里） ============

def fetch_report_by_date(conn, report_date: str):
    """获取指定日期的日报"""
    with conn:
        cur = conn.execute(
            "SELECT report_date, overview, report_json "
            "FROM daily_reports WHERE report_date = ?",
            (report_date,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

def fetch_reports_range(conn, start_date: str, end_date: str):
    """获取日期范围内的日报，按日期倒序"""
    with conn:
        cur = conn.execute(
            "SELECT report_date, overview, report_json "
            "FROM daily_reports WHERE report_date >= ? AND report_date <= ? "
            "ORDER BY report_date DESC",
            (start_date, end_date),
        )
        return [dict(row) for row in cur.fetchall()]

def fetch_news_by_ids(conn, news_ids):
    """按 id 批量取新闻（供日报 enrich 使用）"""
    news_ids = list(news_ids or [])
    if not news_ids:
        return {}
    placeholders = ", ".join("?" for _ in news_ids)
    with conn:
        cur = conn.execute(
            f"""SELECT id, title, source, published, summary, content,
                       llm_category, keywords, importance, url
                FROM news WHERE id IN ({placeholders})""",
            tuple(news_ids),
        )
        return {row["id"]: dict(row) for row in cur.fetchall()}

def table_columns(conn, table_name: str) -> set[str]:
    """
    返回指定表的所有列名集合。
    用于动态判断某个字段是否存在，避免 SELECT/UPDATE 不存在的列。
    """
    cur = conn.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cur.fetchall()}

def table_exists(conn, table_name: str) -> bool:
    """判断某张表是否存在"""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None

# storage/db.py —— 新增
def report_exists(conn, report_date: str) -> bool:
    """检查指定日期的日报是否已存在"""
    row = conn.execute(
        "SELECT 1 FROM daily_reports WHERE report_date = ?",
        (report_date,),
    ).fetchone()
    return row is not None
