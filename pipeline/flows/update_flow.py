# pipeline/flows/update_flow.py
import argparse, fcntl, os, sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from prefect import flow
from pipeline.state import PipelineState, CrawlMode
from pipeline.tasks.crawl_task import crawl_task
from pipeline.tasks.extraction_task import extraction_task
from pipeline.tasks.dedup_task import dedup_task
from pipeline.tasks.analysis_task import analysis_task
from pipeline.tasks.embedding_task import embedding_task
from pipeline.tasks.clustering_task import clustering_task
from pipeline.tasks.report_task import report_task

STAGES = (crawl_task, extraction_task, dedup_task, analysis_task,
          embedding_task, clustering_task, report_task)


@flow(name="news-update-pipeline", log_prints=True)
def update_flow(
    mode: str = "recent",
    year: Optional[int] = None,
    month: Optional[int] = None,
    lookback_days: int = 3,
    max_analyze: int = 150,
):
    # 业务层再校验一次，防止 month 模式缺参数
    if mode == "month" and (year is None or month is None):
        raise ValueError("mode='month' 时必须提供 year 和 month")

    state = PipelineState(
        mode=CrawlMode(mode),
        year=year,
        month=month,
        lookback_days=lookback_days,
        max_analyze=max_analyze,
    )
    for stage in STAGES:
        state = stage(state)

    for name, stats in state.stage_stats.items():
        print(f"  {name}: {stats}")
    for err in state.errors:
        print(f"  ⚠️ {err}")
    return state


def _single_instance():
    """防止两次运行同时抢同一批数据(定时任务重叠时直接跳过)"""
    f = open("/tmp/ai_news_pipeline.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("上一次运行还没结束,本次跳过")
        sys.exit(0)
    return f


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["recent", "month"], default="recent")
    p.add_argument("--year", type=int)
    p.add_argument("--month", type=int)
    p.add_argument("--lookback", type=int, default=3)
    p.add_argument("--max-analyze", type=int, default=150)
    a = p.parse_args()

    # month 模式必须带 year/month（提前报错，比 Prefect 里报清晰得多）
    if a.mode == "month" and (a.year is None or a.month is None):
        p.error("--mode month 需要同时提供 --year 和 --month")

    lock = _single_instance()

    kwargs = {
        "mode": a.mode,
        "lookback_days": a.lookback,
        "max_analyze": a.max_analyze,
    }
    if a.year is not None:
        kwargs["year"] = a.year
    if a.month is not None:
        kwargs["month"] = a.month

    update_flow(**kwargs)