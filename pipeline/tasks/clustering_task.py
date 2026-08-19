
# pipeline/tasks/clustering_task.py  增量版本
# 添加项目根目录到 Python 路径
import os
import sys


project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from prefect import task, get_run_logger
from embedding.incremental_event import run as incremental_cluster_run
from pipeline.state import PipelineState
import sqlite3
from config.database import DB_PATH

@task(name="incremental-clustering", retries=1)
def clustering_task(state: PipelineState) -> PipelineState:
    logger = get_run_logger()

    conn = sqlite3.connect(DB_PATH)
    pending_count = conn.execute(
        "SELECT COUNT(*) FROM news WHERE status = 'embedded'"
    ).fetchone()[0]
    conn.close()

    stats = incremental_cluster_run()   # ⭐ 需要让 main() 返回统计，见下方修改

    state.stage_stats["clustering"] = stats
    logger.info(f"增量聚类: 处理{stats['total']}条, 新建事件{stats['new_events']}, 归入已有{stats['joined_existing']}")
    return state

# # 全量版本
# # pipeline/tasks/clustering_task.py
# from prefect import task, get_run_logger
# from embedding.clustering import init_event_tables, cluster_news, save_clusters
# from pipeline.state import PipelineState

# @task(name="clustering", retries=1)
# def clustering_task(state: PipelineState) -> PipelineState:
#     logger = get_run_logger()
#     init_event_tables()
#     clusters = cluster_news()

#     if not clusters:
#         state.stage_stats["clustering"] = {"event_count": 0, "clustered_news": 0}
#         logger.info("聚类: 无新事件簇生成")
#         return state

#     event_count, clustered_news_count = save_clusters(clusters)
#     state.stage_stats["clustering"] = {
#         "event_count": event_count,
#         "clustered_news": clustered_news_count,
#     }
#     logger.info(f"聚类: 生成{event_count}个事件, 覆盖{clustered_news_count}条新闻")
#     return state