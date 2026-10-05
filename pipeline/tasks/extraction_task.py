# pipeline/tasks/extraction_task.py
from prefect import task, get_run_logger
from ingestion.article_extractor import run as extract_run
from pipeline.state import PipelineState


@task(name="extract-content", retries=1, retry_delay_seconds=30, timeout_seconds=3600)
def extraction_task(state: PipelineState) -> PipelineState:
    logger = get_run_logger()
    stats = extract_run()          # 不传窗口: 处理所有 raw + 可重试的 extract_failed
    state.stage_stats["extraction"] = stats
    logger.info(f"正文提取: 成功{stats['success']} 失败{stats['failed']}")
    return state