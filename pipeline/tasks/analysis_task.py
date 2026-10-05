# pipeline/tasks/analysis_task.py
from prefect import task, get_run_logger
from agent.news_analyzer import run as analyze_run  # 按你的实际模块路径
from pipeline.state import PipelineState


@task(name="llm-analysis", retries=1, retry_delay_seconds=30, timeout_seconds=3600)
def analysis_task(state: PipelineState) -> PipelineState:
    logger = get_run_logger()
    stats = analyze_run(max_items=state.max_analyze, per_source_cap=state.per_source_cap)
    state.stage_stats["analysis"] = stats
    logger.info(f"LLM分析: 成功{stats['success']} 失败{stats['failed']}")
    if stats["total"] and stats["failed"] / stats["total"] > 0.3:
        state.errors.append(f"analysis: 失败率过高 {stats['failed']}/{stats['total']}")
    return state