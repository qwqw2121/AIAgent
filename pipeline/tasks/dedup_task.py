# pipeline/tasks/dedup_task.py
from prefect import task, get_run_logger
from ingestion.dedup import run as dedup_run
from pipeline.state import PipelineState


@task(name="dedup-titles", retries=1)
def dedup_task(state: PipelineState) -> PipelineState:
    logger = get_run_logger()
    stats = dedup_run()
    state.stage_stats["dedup"] = stats
    logger.info(f"去重: 存活{stats['survived']} 精确重复{stats['exact_dup']} 模糊重复{stats['fuzzy_dup']}")
    return state