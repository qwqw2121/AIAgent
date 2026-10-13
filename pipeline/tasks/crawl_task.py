from datetime import timedelta
from prefect import task, get_run_logger
from ingestion.rss_crawler import run as crawl_run
from pipeline.state import PipelineState, CrawlMode

@task(name="crawl-rss", retries=1, retry_delay_seconds=30, timeout_seconds=900)
def crawl_task(state: PipelineState) -> PipelineState:
    logger = get_run_logger()

    if state.run_date is not None:
        # 指定日期：只抓这一天
        stats = crawl_run(target_date=state.run_date)
        logger.info(f"按天抓取 {state.run_date}")  
    elif state.mode == CrawlMode.MONTH:
        stats = crawl_run(target_year=state.year, target_month=state.month)
        logger.info(f"按月抓取 {state.year}-{state.month:02d}")
    else:
        # RECENT：逐天抓取，合并结果
        today = state.run_at.date()
        stats = None
        for i in range(state.lookback_days):
            d = today - timedelta(days=i)
            day_stats = crawl_run(target_date=d)
            logger.info(
                f"[{d}] 抓取 {day_stats['total_fetched']}, "
                f"入库 {day_stats['total_inserted']}, "
                f"跳过 {day_stats['total_skipped']}"
            )
            if stats is None:
                stats = day_stats
            else:
                stats["total_fetched"] += day_stats["total_fetched"]
                stats["total_inserted"] += day_stats["total_inserted"]
                stats["total_skipped"] += day_stats["total_skipped"]
                stats["failed_sources"].extend(day_stats["failed_sources"])
                stats["per_source"].extend(day_stats["per_source"])
        logger.info(f"增量抓取最近 {state.lookback_days} 天")

    state.stage_stats["crawl"] = {k: v for k, v in stats.items() if k != "per_source"}
    logger.info(f"抓取 {stats['total_fetched']}, 入库 {stats['total_inserted']}, "
                f"跳过 {stats['total_skipped']}, 失败源 {len(stats['failed_sources'])}")

    if stats["failed_sources"]:
        state.errors.append(f"crawl: {len(stats['failed_sources'])} 个源失败")
    return state