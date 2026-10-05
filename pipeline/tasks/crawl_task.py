# pipeline/tasks/crawl_task.py
from prefect import task, get_run_logger
from ingestion.rss_crawler import run as crawl_run
from pipeline.state import PipelineState, CrawlMode


@task(name="crawl-rss", retries=1, retry_delay_seconds=30, timeout_seconds=900)
def crawl_task(state: PipelineState) -> PipelineState:
    logger = get_run_logger()

    if state.mode == CrawlMode.MONTH:
        stats = crawl_run(target_year=state.year, target_month=state.month)
        logger.info(f"按月抓取 {state.year}-{state.month:02d}")
    else:
        stats = crawl_run(since_ts=state.since_ts())
        logger.info(f"增量抓取最近 {state.lookback_days} 天")

    state.stage_stats["crawl"] = {k: v for k, v in stats.items() if k != "per_source"}
    logger.info(f"抓取 {stats['total_fetched']}, 入库 {stats['total_inserted']}, "
                f"跳过 {stats['total_skipped']}, 失败源 {len(stats['failed_sources'])}")

    if stats["failed_sources"]:
        state.errors.append(f"crawl: {len(stats['failed_sources'])} 个源失败")
    return state