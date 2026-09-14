''' 
daily_news_flow.py
'''

# pipeline/flows/daily_flow.py
import sys
import os
# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
                                   
from prefect import flow
from datetime import date, timedelta
from pipeline.state import PipelineState
from pipeline.tasks.crawl_task import crawl_task
from pipeline.tasks.extraction_task import extraction_task
from pipeline.tasks.dedup_task import dedup_task
from pipeline.tasks.analysis_task import analysis_task
from pipeline.tasks.embedding_task import embedding_task
from pipeline.tasks.clustering_task import clustering_task
from pipeline.tasks.report_task import report_task


@flow(name="daily-news-pipeline", log_prints=True)
def daily_flow(run_date: date = None):
    target_date = run_date or (date.today() - timedelta(days=1))
    state = PipelineState(run_date=target_date)

    state = crawl_task(state)
    state = extraction_task(state)
    state = dedup_task(state)
    state = analysis_task(state)
    state = embedding_task(state)
    state = clustering_task(state)
    state = report_task(state)

    print("=== 本次运行统计 ===")
    for stage, stats in state.stage_stats.items():
        print(f"  {stage}: {stats}")

    if state.errors:
        print("⚠️ 本次运行存在告警:")
        for err in state.errors:
            print(f"  - {err}")

    return state


if __name__ == "__main__":
    daily_flow(run_date=date.today() - timedelta(days=1))
    # daily_flow(run_date=date(2026, 9, 1))