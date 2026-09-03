 # Prefect 部署/调度配置（cron、告警等）

 # pipeline/deployments.py
from pipeline.flows.daily_news_flow import daily_flow

if __name__ == "__main__":
    daily_flow.deploy(
        name="daily-news-deployment",
        work_pool_name="default-work-pool",
        cron="0 8 * * *",
    )