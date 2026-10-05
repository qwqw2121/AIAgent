"""
pipeline/flows/daily_flow.py

单日 AI 新闻处理流程
"""
import faulthandler
faulthandler.dump_traceback_later(60, exit=False)


import os
import sys
from datetime import date, timedelta

# 添加项目根目录到 Python 路径
sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
    )
)

from prefect import flow

from pipeline.state import PipelineState
from pipeline.tasks.crawl_task import crawl_task
from pipeline.tasks.extraction_task import extraction_task
from pipeline.tasks.dedup_task import dedup_task
from pipeline.tasks.analysis_task import analysis_task
from pipeline.tasks.embedding_task import embedding_task
from pipeline.tasks.clustering_task import clustering_task
from pipeline.tasks.report_task import report_task


@flow(
    name="daily-news-pipeline",
    log_prints=True,
)
def daily_flow(run_date: date = None):

    target_date = run_date or (
        date.today() - timedelta(days=1)
    )

    print("=" * 60)
    print(f"开始处理日期：{target_date}")
    print("=" * 60)

    state = PipelineState(run_date=target_date)

    # ① RSS 抓取
    state = crawl_task(state)

    # ② 正文提取
    state = extraction_task(state)

    # ③ 去重
    state = dedup_task(state)

    # ④ LLM 分析
    state = analysis_task(state)

    # ⑤ Embedding
    state = embedding_task(state)

    # ⑥ 事件聚类
    state = clustering_task(state)

    # ⑦ 日报生成
    state = report_task(state)

    # =========================
    # 运行统计
    # =========================

    print()
    print("=== 本次运行统计 ===")

    for stage, stats in state.stage_stats.items():
        print(f"  {stage}: {stats}")

    # =========================
    # 错误信息
    # =========================

    if state.errors:

        print()
        print("⚠️ 本次运行存在告警：")

        for err in state.errors:
            print(f"  - {err}")

    else:
        print("✅ 本次运行没有错误")

    print()
    print(f"日期 {target_date} 处理完成")
    print("=" * 60)

    return state


if __name__ == "__main__":

    daily_flow(
        run_date=date.today() - timedelta(days=1)
    )