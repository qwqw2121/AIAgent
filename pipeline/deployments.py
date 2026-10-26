# pipeline/deployments.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from prefect import flow
from prefect.schedules import Cron   # 需要 Prefect >= 3.1

POOL = "default-work-pool"
SOURCE = str(ROOT)                    # 容器里就是 /app
ENTRY = "pipeline/flows/scheduled_flow.py"


def deploy_all():
    # 北京 08:30：补齐昨日日报 + 抓取今日新闻
    flow.from_source(
        source=SOURCE, entrypoint=f"{ENTRY}:morning_flow"
    ).deploy(
        name="morning-0830-cst",
        work_pool_name=POOL,
        schedule=Cron("30 0 * * *", timezone="UTC"),
    )

    # 北京 12:00 / 16:00 / 20:00：只抓取和分析，供首页「重要新闻」
    flow.from_source(
        source=SOURCE, entrypoint=f"{ENTRY}:intraday_flow"
    ).deploy(
        name="intraday-every-3h",
        work_pool_name=POOL,
        schedule=Cron("0 4,8,12 * * *", timezone="UTC"),
    )

    # 可选：只用于在 UI 里手动补跑某一天，没有定时
    flow.from_source(
        source=SOURCE, entrypoint="pipeline/flows/daily_news_flow.py:daily_flow"
    ).deploy(
        name="daily-manual",
        work_pool_name=POOL,
    )


if __name__ == "__main__":
    deploy_all()