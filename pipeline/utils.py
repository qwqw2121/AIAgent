# pipeline/utils.py
from datetime import date, datetime, timedelta, timezone

TZ_HOURS = 0                              # UTC
TZ = timezone(timedelta(hours=TZ_HOURS))
SQL_TZ = f"{TZ_HOURS:+d} hours"           # "+0 hours"，SQLite 可识别

def day_bounds_ts(day: str):
    """某天 UTC [00:00, 24:00) 对应的时间戳区间"""
    d = date.fromisoformat(day)
    start = datetime.combine(d, datetime.min.time(), tzinfo=TZ)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())