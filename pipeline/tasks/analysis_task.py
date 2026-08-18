# pipeline/tasks/analysis_task.py
from prefect import task, get_run_logger
from ingestion.analysis.news_analyzer import run as analyze_run
from pipeline.state import PipelineState

@task(name="llm-analysis", retries=1)  # 内部已有 max_retry 重试单条，外层重试次数不宜太高
def analysis_task(state: PipelineState) -> PipelineState:
    logger = get_run_logger()
    # dedup 后状态是 'deduped'，analyzer 目前查 ('extracted','analyze_failed')，
    # 需要同步把 analyzer 的查询条件改成 ('deduped', 'analyze_failed')
    stats = analyze_run(sleep_sec=0.3, max_retry=3)
    state.stage_stats["analysis"] = stats
    logger.info(f"LLM分析: 成功{stats['success']} 失败{stats['failed']}")
    if stats["total"] > 0 and stats["failed"] / stats["total"] > 0.3:
        state.errors.append(f"analysis: LLM分析失败率过高 {stats['failed']}/{stats['total']}")
    return state