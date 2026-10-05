"""
pipeline/flows/batch_daily_flow.py

批量生成多个日期的日报。

特点：
1. 支持日期范围
2. 多日期并发
3. 最大并发数可配置
4. 单日失败不会影响其他日期
5. Prefect UI 可以看到每个日期的执行情况
"""

import os
import sys

from datetime import date, timedelta

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 添加项目根目录到 Python 路径
# ============================================================

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
    )
)


from prefect import flow

from pipeline.flows.daily_news_flow import daily_flow


# ============================================================
# 单日执行包装器
# ============================================================

def run_single_day(run_date: date):

    print(f"🚀 开始提交：{run_date}")

    try:

        state = daily_flow(
            run_date=run_date
        )

        return {
            "date": run_date,
            "success": True,
            "state": state,
            "error": None,
        }

    except Exception as e:

        print(
            f"❌ {run_date} 执行失败：{e}"
        )

        return {
            "date": run_date,
            "success": False,
            "state": None,
            "error": str(e),
        }


# ============================================================
# 日期生成
# ============================================================

def generate_dates(
    start_date: date,
    end_date: date,
):

    dates = []

    current_date = start_date

    while current_date <= end_date:

        dates.append(current_date)

        current_date += timedelta(days=1)

    return dates


# ============================================================
# 批量 Flow
# ============================================================

@flow(
    name="batch-daily-news-pipeline",
    log_prints=True,
)
def batch_daily_flow(
    start_date: date,
    end_date: date,
    max_concurrency: int = 2,
):

    # ========================================================
    # 生成日期
    # ========================================================

    dates = generate_dates(
        start_date,
        end_date,
    )

    print()
    print("=" * 70)
    print("批量日报任务")
    print("=" * 70)

    print(f"开始日期：{start_date}")
    print(f"结束日期：{end_date}")
    print(f"共计日期：{len(dates)}")
    print(f"最大并发：{max_concurrency}")

    print()
    print("待处理日期：")

    for d in dates:
        print(f"  - {d}")

    print("=" * 70)
    print()

    # ========================================================
    # 并发执行
    # ========================================================

    results = []

    with ThreadPoolExecutor(
        max_workers=max_concurrency
    ) as executor:

        future_map = {
            executor.submit(
                run_single_day,
                d
            ): d
            for d in dates
        }

        # ====================================================
        # 谁先完成就先处理谁
        # ====================================================

        for future in as_completed(
            future_map
        ):

            run_date = future_map[future]

            try:

                result = future.result()

                results.append(result)

            except Exception as e:

                results.append(
                    {
                        "date": run_date,
                        "success": False,
                        "state": None,
                        "error": str(e),
                    }
                )

    # ========================================================
    # 排序
    # ========================================================

    results.sort(
        key=lambda x: x["date"]
    )

    # ========================================================
    # 最终统计
    # ========================================================

    print()
    print("=" * 70)
    print("批量任务完成")
    print("=" * 70)

    success_count = 0
    failed_count = 0

    for result in results:

        run_date = result["date"]

        if result["success"]:

            success_count += 1

            print(
                f"✅ {run_date}：成功"
            )

        else:

            failed_count += 1

            print(
                f"❌ {run_date}：失败"
            )

            print(
                f"   错误：{result['error']}"
            )

    print()
    print(f"总日期：{len(results)}")
    print(f"成功：{success_count}")
    print(f"失败：{failed_count}")

    print("=" * 70)

    return results


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    batch_daily_flow(
        start_date=date(2026, 9, 17),
        end_date=date(2026, 9, 20),

        # 建议先从 2 开始
        max_concurrency=1,
    )