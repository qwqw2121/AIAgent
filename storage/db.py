# storage/db.py
"""
兼容门面：对外导入路径保持 `from storage.db import ...` 不变，
实现已按职责拆到 connection / news_repo / report_repo / trend_repo。
"""
from storage.connection import (
    DB_PATH, DONE_STATUSES, SUMMARY_EXPR,
    _connect, init_db, get_connection,
    all_dicts, one_dict, table_columns, table_exists,
)
from storage.news_repo import (
    update_fields, fetch_by_status, query_news,
    fetch_news_by_ids, fetch_important_recent,
)
from storage.report_repo import (
    fetch_report_by_date, fetch_reports_range, report_exists,
    fetch_latest_report, fetch_all_report_indexes,
)
from storage.trend_repo import (
    normalize_keyword, fetch_trends, fetch_tech_news, _has_keyword,
)

# 旧名字别名，防止其他模块还在用
_SUMMARY_EXPR = SUMMARY_EXPR
_all_dicts = all_dicts
_one_dict = one_dict

__all__ = [
    "DB_PATH", "DONE_STATUSES", "init_db", "get_connection",
    "table_columns", "table_exists",
    "update_fields", "fetch_by_status", "query_news",
    "fetch_news_by_ids", "fetch_important_recent",
    "fetch_report_by_date", "fetch_reports_range", "report_exists",
    "fetch_latest_report", "fetch_all_report_indexes",
    "normalize_keyword", "fetch_trends", "fetch_tech_news",
]