# pipeline/tasks/report_task.py
from prefect import task, get_run_logger
from agent.daily_report import create_daily_report
from pipeline.state import PipelineState

@task(name="daily-report", retries=1)
def report_task(state: PipelineState) -> PipelineState:
    logger = get_run_logger()
    report = create_daily_report(state.run_date.isoformat())

    if report is None:
        state.errors.append("report: 当天没有可用新闻，未生成日报")
        state.stage_stats["report"] = {"generated": False}
    else:
        event_count = len(report.get("events", []))
        state.stage_stats["report"] = {"generated": True, "event_count": event_count}
        logger.info(f"日报生成完成，包含 {event_count} 个事件")

    return state