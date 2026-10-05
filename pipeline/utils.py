from datetime import date, datetime, timedelta, timezone

TZ_HOURS = 8   # 网站"一天"的划分时区: 北京/新加坡 8, 东京/大阪 9, UTC 0
TZ = timezone(timedelta(hours=TZ_HOURS))
SQL_TZ = f"{TZ_HOURS:+d} hours"      # 用于 date(published_ts,'unixepoch','+8 hours')

def day_bounds_ts(day: str):
    """本地时区某一天 [00:00, 24:00) 对应的 UTC 时间戳区间"""
    d = date.fromisoformat(day)
    start = datetime.combine(d, datetime.min.time(), tzinfo=TZ)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())