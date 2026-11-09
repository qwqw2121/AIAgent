"""
自然语言查询解析：
1. 识别明确日期和相对时间范围
2. 从原始查询中移除时间表达式
3. 清理常见口语化填充词
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("Asia/Shanghai")


# 查询中常见的无实际检索意义的词
FILLERS = (
    "帮我", "请问", "查找", "搜索", "获取",
    "看看", "列出", "相关新闻", "相关", "关于",
    "有关", "最新", "新闻", "一下", "的",
)


def _month_range(year: int, month: int):
    """返回指定月份的开始和结束时间。"""
    start = datetime(year, month, 1, tzinfo=TIMEZONE)

    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=TIMEZONE)
    else:
        end = datetime(year, month + 1, 1, tzinfo=TIMEZONE)

    return start, end


def parse_query(query: str) -> dict:
    """
    返回：
    {
        "query": 检索关键词,
        "start_ts": 开始时间戳（包含）,
        "end_ts": 结束时间戳（不包含）
    }

    时间语义：
    - 最近一周：过去 7 天
    - 本周、这周：本周周一 00:00 至当前时间
    - 最近一个月：过去 30 天
    - 本月：本月 1 日至当前时间
    """

    q = (query or "").strip()

    now = datetime.now(TIMEZONE)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    start = None
    end = None
    matched = None

    # 1. 明确年月：2026年10月、2026-10
    m = re.search(r"(\d{4})年(\d{1,2})月", q)

    if not m:
        m = re.search(r"(\d{4})-(\d{1,2})(?!\d)", q)

    if m:
        year, month = map(int, m.groups())

        if 1 <= month <= 12:
            start, end = _month_range(year, month)
            matched = m.group()

    # 2. 相对时间
    if start is None:

        # 本周：从周一零点开始，而不是滚动 7 天
        week_terms = ("本周", "这周")

        if any(x in q for x in week_terms):
            monday = today - timedelta(days=today.weekday())
            start = monday
            end = now
            matched = next(x for x in week_terms if x in q)

        # 最近一周：滚动过去 7 天
        elif any(x in q for x in ("最近一周", "近一周", "过去一周")):
            matched = next(
                x for x in ("最近一周", "近一周", "过去一周")
                if x in q
            )
            start = now - timedelta(days=7)
            end = now

        # 最近 N 周，例如最近 2 周、过去 3 周
        else:
            m = re.search(
                r"(?:最近|近|过去)\s*(\d+)\s*周",
                q,
            )

            if m:
                weeks = int(m.group(1))
                if weeks > 0:
                    start = now - timedelta(weeks=weeks)
                    end = now
                    matched = m.group()

        # 最近 N 天，例如最近7天、近 7 天、过去 7 天
        if start is None:
            m = re.search(
                r"(?:最近|近|过去)\s*(\d+)\s*天",
                q,
            )

            if m:
                days = int(m.group(1))
                if days > 0:
                    start = now - timedelta(days=days)
                    end = now
                    matched = m.group()

        # 最近一个月：按滚动 30 天计算
        if start is None:
            month_terms = ("最近一个月", "近一个月", "过去一个月")

            if any(x in q for x in month_terms):
                matched = next(x for x in month_terms if x in q)
                start = now - timedelta(days=30)
                end = now

        # 本月：自然月
        if start is None:
            month_terms = ("当月", "本月", "这个月")

            if any(x in q for x in month_terms):
                matched = next(x for x in month_terms if x in q)
                start = today.replace(day=1)
                end = now

        # 今天
        if start is None:
            day_terms = ("今天", "今日")

            if any(x in q for x in day_terms):
                matched = next(x for x in day_terms if x in q)
                start = today
                end = now

        # 昨天
        if start is None:
            day_terms = ("昨天", "昨日")

            if any(x in q for x in day_terms):
                matched = next(x for x in day_terms if x in q)
                start = today - timedelta(days=1)
                end = today

    # 3. 移除已经识别的时间表达式
    clean_query = q

    if matched:
        clean_query = clean_query.replace(matched, " ", 1)

    # 4. 移除口语化填充词
    for word in FILLERS:
        clean_query = clean_query.replace(word, " ")

    clean_query = re.sub(r"\s+", " ", clean_query).strip()

    return {
        "query": clean_query,
        "start_ts": int(start.timestamp()) if start else None,
        "end_ts": int(end.timestamp()) if end else None,
    }