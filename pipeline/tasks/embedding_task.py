# pipeline/tasks/embedding_task.py
from prefect import task, get_run_logger
from embedding.embed_news import run as embed_run
from pipeline.state import PipelineState

@task(name="embedding", retries=1, retry_delay_seconds=60)
def embedding_task(state: PipelineState) -> PipelineState:
    logger = get_run_logger()
    stats = embed_run()
    state.stage_stats["embedding"] = stats
    logger.info(f"Embedding: 成功{stats['success']} 失败{stats['failed']}")
    if stats["total"] > 0 and stats["failed"] / stats["total"] > 0.3:
        state.errors.append(f"embedding: 失败率过高 {stats['failed']}/{stats['total']}")
    return state