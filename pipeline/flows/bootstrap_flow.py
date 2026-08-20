# 首次建库是一次性操作，不适合放进每日自动 flow，建议做成独立的手动触发命令（或者一个单独的 bootstrap_flow）：
# pipeline/flows/bootstrap_flow.py
from prefect import flow
from embedding.clustering import init_event_tables, cluster_news, save_clusters

@flow(name="bootstrap-event-clustering")
def bootstrap_flow():
    """
    首次建库专用：对当前所有 embedded 新闻做一次全量 DBSCAN 聚类。
    只手动运行一次，之后的增量新闻交给 daily_flow 里的 incremental_clustering_task 处理。
    """
    init_event_tables()
    clusters = cluster_news()
    if clusters:
        save_clusters(clusters)


if __name__ == "__main__":
    bootstrap_flow()

#这样职责很清楚：clustering.py 是"地基"，跑一次；
# incremental_event.py 是"日常维护"，每天跑。两者共用同一套 events/event_news 表结构，互不冲突。