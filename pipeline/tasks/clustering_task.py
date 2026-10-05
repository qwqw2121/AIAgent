# pipeline/tasks/clustering_task.py
from prefect import task, get_run_logger
from embedding.incremental_event import run as incremental_cluster_run
from pipeline.state import PipelineState
from pipeline.utils import day_bounds_ts

@task(name="incremental-clustering", retries=1)
def clustering_task(state: PipelineState) -> PipelineState:
    logger = get_run_logger()
    start_ts, end_ts = day_bounds_ts(state.run_date)
    stats = incremental_cluster_run(start_ts, end_ts)

    state.stage_stats["clustering"] = stats
    logger.info(
        f"增量聚类: 处理{stats['total']}条, 新建事件{stats['new_events']}, "
        f"归入已有{stats['joined_existing']}, 失败{stats['failed']}"
    )
    if stats["failed"] > 0:
        state.errors.append(f"clustering: {stats['failed']} 条处理失败")
    return state