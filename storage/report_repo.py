# storage/report_repo.py
"""日报表读取"""
from storage.connection import all_dicts, one_dict


def fetch_report_by_date(conn, report_date: str):
    cur = conn.execute(
        "SELECT report_date, overview, report_json "
        "FROM daily_reports WHERE report_date = ?",
        (report_date,),
    )
    return one_dict(cur)


def fetch_reports_range(conn, start_date: str, end_date: str):
    cur = conn.execute(
        "SELECT report_date, overview, report_json "
        "FROM daily_reports WHERE report_date >= ? AND report_date <= ? "
        "ORDER BY report_date DESC",
        (start_date, end_date),
    )
    return all_dicts(cur)


def report_exists(conn, report_date: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM daily_reports WHERE report_date = ?", (report_date,)
    ).fetchone() is not None


def fetch_latest_report(conn):
    return conn.execute(
        """
        SELECT *
        FROM daily_reports
        ORDER BY report_date DESC
        LIMIT 1
        """
    ).fetchone()


def fetch_all_report_indexes(conn):
    return conn.execute(
        """
        SELECT report_date, overview, report_json
        FROM daily_reports
        ORDER BY report_date DESC
        """
    ).fetchall()