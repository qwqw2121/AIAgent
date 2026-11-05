import threading
import time

# key: YYYY-MM-DD
# value: 任务开始时间
_jobs: dict[str, float] = {}

STALE_SECONDS = 15 * 60
_lock = threading.Lock()


def mark_generating(report_date: str) -> None:
    """标记指定日期的日报正在生成。"""
    with _lock:
        _jobs[report_date] = time.time()


def mark_done(report_date: str) -> None:
    """清除指定日期的生成状态。"""
    with _lock:
        _jobs.pop(report_date, None)


def is_generating(report_date: str) -> bool:
    """判断指定日期的日报是否正在生成。"""
    with _lock:
        started_at = _jobs.get(report_date)

        if started_at is None:
            return False

        if time.time() - started_at > STALE_SECONDS:
            _jobs.pop(report_date, None)
            return False

        return True