 # Prefect 部署/调度配置（cron、告警等）

 # pipeline/deployments.py
from prefect.deployments import Deployment
from pipeline.flows.daily_news_flow import daily_news_flow
from prefect.server.schemas.schedules import CronSchedule

deployment = Deployment.build_from_flow(
    flow=daily_news_flow,
    name="daily-news-deployment",
    work_pool_name="default-work-pool",
    # 每天早上 8:00 自动运行
    schedule=CronSchedule(cron="0 8 * * *"), 
)

if __name__ == "__main__":
    deployment.apply()