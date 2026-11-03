# pipeline/config.py
"""聚类与日报共用的阈值，改这里一处即可。"""

MIN_NEWS_IMPORTANCE = 3           # importance > 3 才参与聚类
MIN_EVENT_SIZE = 2                # 多源事件：至少 2 条
SINGLE_EVENT_MIN_IMPORTANCE = 7   # 单条新闻达到该分数可单独成条
MIN_REPORT_EVENTS = 6             # 日报保底条数