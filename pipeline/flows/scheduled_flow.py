"""
pipeline/flows/scheduled_flow.py

morning_flow  : 每天北京 08:30 -> 生成/补齐昨日日报 + 抓取分析今日截至当前的新闻
intraday_flow : 白天每 3 小时 -> 只抓取+分析新闻（供首页「重要新闻」）
"""
import os
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from datetime import date
from typing import Optional

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from prefect import flow, serve

from pipeline.state import PipelineState
from pipeline.tasks.crawl_task import crawl_task
from pipeline.tasks.extraction_task import extraction_task
from pipeline.tasks.dedup_task import dedup_task
from pipeline.tasks.analysis_task import analysis_task
from pipeline.flows.batch_daily_flow import batch_daily_flow

try:
    import fcntl          # 仅 Linux/macOS；Windows 本地调试时自动跳过锁
except ImportError:
    fcntl = None

LOCK_PATH = os.getenv("PIPELINE_LOCK_PATH", "/tmp/news_pipeline.lock")


class PipelineBusy(RuntimeError):
    pass


@contextmanager
def pipeline_lock():
    """防止两个流水线同时跑（同时写 SQLite、重复调 LLM）"""
    if fcntl is None:
        yield
        return
    f = open(LOCK_PATH, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        raise PipelineBusy("另一个流水线正在运行")
    try:
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _intraday_body(target: date):
    """抓取 -> 提取 -> 去重 -> LLM 分析(含 importance)；不生成日报"""
    state = PipelineState(run_date=target)
    state = crawl_task(state)
    state = extraction_task(state)
    state = dedup_task(state)
    state = analysis_task(state)
    return state


@flow(name="intraday-news-pipeline", log_prints=True)
def intraday_flow(run_date: Optional[date] = None):
    target = run_date or today_utc()
    try:
        with pipeline_lock():
            print(f"[intraday] 处理 {target}（UTC 天）截至当前的新闻")
            return _intraday_body(target)
    except PipelineBusy:
        print("[intraday] 其他流水线正在运行，本次跳过")


@flow(name="morning-pipeline", log_prints=True)
def morning_flow(backfill_days: int = 3):
    today = today_utc()
    yesterday = today - timedelta(days=1)
    problems = []

    with pipeline_lock():
        # ① 补齐更早缺失的日报（已有的自动跳过）
        if backfill_days > 1:
            results = batch_daily_flow(
                start_date=yesterday - timedelta(days=backfill_days - 1),
                end_date=yesterday - timedelta(days=1),
                max_concurrency=1,      # SQLite 写入，先用 1 更稳
                force=False,
            )
            problems += [r["date"] for r in results if not r["success"]]

        # ② 昨日日报：强制重生成。
        #    因为白天 intraday 或手动测试可能已产生过不完整的日报
        results = batch_daily_flow(
            start_date=yesterday, end_date=yesterday,
            max_concurrency=1, force=True,
        )
        problems += [r["date"] for r in results if not r["success"]]

        # ③ 今日截至当前的新闻
        try:
            _intraday_body(today)
        except Exception as e:
            print(f"❌ 今日新闻阶段失败：{e}")

    if problems:
        # 抛出异常，Prefect 才会把这次运行标红，方便告警
        raise RuntimeError(f"以下日期日报生成失败：{problems}")


if __name__ == "__main__":
    # cron 按 UTC：30 0 * * * = 北京 08:30；2-14/3 = 北京 10/13/16/19/22 点cron="0 2-14/3 * * *"
    morning = morning_flow.to_deployment(
        name="morning-0830-cst", cron="30 0 * * *")
    intraday = intraday_flow.to_deployment(
        name="intraday-every-3h", cron="0 4,8,12 * * *")
    #UTC 4 → 北京 12:00，UTC 8 → 北京 16:00，UTC 12 → 北京 20:00。
    
    serve(morning, intraday)