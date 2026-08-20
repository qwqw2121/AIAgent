# pipeline/tasks/extraction_task.py

from prefect import task, get_run_logger
from ingestion.article_extractor import run as extract_run
from pipeline.state import PipelineState

@task(name="extract-content", retries=2, retry_delay_seconds=30)
def extraction_task(state: PipelineState) -> PipelineState:
    logger = get_run_logger()
    stats = extract_run()
    state.stage_stats["extraction"] = stats
    logger.info(f"正文提取: 成功{stats['success']} 失败{stats['failed']}")
    if stats["total"] > 0 and stats["failed"] / stats["total"] > 0.5:
        state.errors.append(f"extraction: 失败率过高 {stats['failed']}/{stats['total']}，请检查目标站点是否反爬")
    return state