# pipeline/tasks/crawl_task.py
from prefect import task, get_run_logger
from ingestion.rss_crawler import run as crawl_rss_sources
from pipeline.state import PipelineState


@task(name="crawl-rss", retries=3, retry_delay_seconds=60, log_prints=True)
def crawl_task(state: PipelineState) -> PipelineState:
    logger = get_run_logger()

    stats = crawl_rss_sources(
        target_year=state.run_date.year,
        target_month=state.run_date.month,
    )

    state.stage_stats["crawl"] = stats
    logger.info(
        f"采集完成: 抓取 {stats['total_fetched']} 条, "
        f"入库 {stats['total_inserted']} 条, 去重跳过 {stats['total_skipped']} 条"
    )

    # 业务规则判断放在 Task 层：这次没抓到任何数据，视为异常，记录但不中断整个 pipeline
    if stats["total_fetched"] == 0:
        state.errors.append("crawl: 本次未采集到任何符合条件的新闻，请检查 RSS 源是否可用")

    return state