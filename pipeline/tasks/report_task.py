# pipeline/tasks/report_task.py
from prefect import task, get_run_logger
from agent.daily_report import create_daily_report, find_pending_dates
from pipeline.state import PipelineState


@task(name="daily-report", retries=1, timeout_seconds=1800)
def report_task(state: PipelineState) -> PipelineState:
    logger = get_run_logger()
    dates = find_pending_dates(limit=state.max_report_days)

    updated = []
    for d in dates:
        try:
            if create_daily_report(d):
                updated.append(d)
        except Exception as e:
            state.errors.append(f"report {d}: {e}")

    state.stage_stats["report"] = {"pending_dates": dates, "updated": updated}
    logger.info(f"日报已更新: {updated}")
    return state