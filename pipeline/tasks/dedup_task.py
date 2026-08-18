# pipeline/tasks/dedup_task.py
from prefect import task, get_run_logger
from ingestion.dedup.dedup import run as dedup_run
from pipeline.state import PipelineState
import sqlite3
from config import DB_PATH

@task(name="dedup-titles", retries=1)
def dedup_task(state: PipelineState) -> PipelineState:
    logger = get_run_logger()
    dedup_run()  # 目前 dedup.run() 不返回统计，用一次查询补上

    conn = sqlite3.connect(DB_PATH)
    deduped_count = conn.execute(
        "SELECT COUNT(*) FROM news WHERE status = 'deduped'"
    ).fetchone()[0]
    dup_count = conn.execute(
        "SELECT COUNT(*) FROM news WHERE is_duplicate = 1"
    ).fetchone()[0]
    conn.close()

    state.stage_stats["dedup"] = {"deduped": deduped_count, "marked_duplicate": dup_count}
    logger.info(f"去重: 存活{deduped_count} 标记重复{dup_count}")
    return state