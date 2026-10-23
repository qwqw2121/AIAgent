"""
pipeline/flows/batch_daily_flow.py

批量生成多个日期的日报。

特点：
1. 支持日期范围
2. 已有日报的日期自动跳过（force=True 可强制重跑）
3. 多日期并发，最大并发数可配置
4. 单日失败不会影响其他日期
5. 失败后直接重跑同一命令，只会补缺的日期
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
from storage.db import get_connection, fetch_report_by_date


# ============================================================
# 判断某天日报是否已存在
# ============================================================

def report_exists(run_date: date) -> bool:
    conn = get_connection()
    try:
        row = fetch_report_by_date(conn, run_date.isoformat())
        return row is not None
    finally:
        conn.close()


# ============================================================
# 单日执行包装器
# ============================================================

def run_single_day(run_date: date, force: bool = False):

    # 已有日报 -> 跳过
    if not force:
        try:
            if report_exists(run_date):
                print(f"⏭️ {run_date} 已有日报，跳过")
                return {
                    "date": run_date,
                    "success": True,
                    "skipped": True,
                    "state": None,
                    "error": None,
                }
        except Exception as e:
            # 查库失败时不要误跳过，继续往下执行
            print(f"⚠️ {run_date} 检查日报是否存在时出错：{e}，将继续生成")

    print(f"🚀 开始提交：{run_date}")

    try:
        state = daily_flow(run_date=run_date)

        return {
            "date": run_date,
            "success": True,
            "skipped": False,
            "state": state,
            "error": None,
        }

    except Exception as e:
        print(f"❌ {run_date} 执行失败：{e}")

        return {
            "date": run_date,
            "success": False,
            "skipped": False,
            "state": None,
            "error": str(e),
        }


# ============================================================
# 日期生成
# ============================================================

def generate_dates(start_date: date, end_date: date):

    if start_date > end_date:
        raise ValueError(
            f"开始日期 {start_date} 不能晚于结束日期 {end_date}"
        )

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
    force: bool = False,
):

    # ========================================================
    # 生成日期
    # ========================================================

    dates = generate_dates(start_date, end_date)

    print()
    print("=" * 70)
    print("批量日报任务")
    print("=" * 70)

    print(f"开始日期：{start_date}")
    print(f"结束日期：{end_date}")
    print(f"共计日期：{len(dates)}")
    print(f"最大并发：{max_concurrency}")
    print(f"强制重跑：{'是' if force else '否（已有日报自动跳过）'}")
    print("=" * 70)
    print()

    # ========================================================
    # 并发执行
    # ========================================================

    results = []

    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:

        future_map = {
            executor.submit(run_single_day, d, force): d
            for d in dates
        }

        # 谁先完成就先处理谁
        for future in as_completed(future_map):

            run_date = future_map[future]

            try:
                results.append(future.result())

            except Exception as e:
                results.append(
                    {
                        "date": run_date,
                        "success": False,
                        "skipped": False,
                        "state": None,
                        "error": str(e),
                    }
                )

    # ========================================================
    # 排序
    # ========================================================

    results.sort(key=lambda x: x["date"])

    # ========================================================
    # 最终统计
    # ========================================================

    skipped = [r for r in results if r.get("skipped")]
    succeeded = [r for r in results if r["success"] and not r.get("skipped")]
    failed = [r for r in results if not r["success"]]

    print()
    print("=" * 70)
    print("批量任务完成")
    print("=" * 70)

    for r in results:
        if r.get("skipped"):
            print(f"⏭️ {r['date']}：已存在，跳过")
        elif r["success"]:
            print(f"✅ {r['date']}：成功")
        else:
            print(f"❌ {r['date']}：失败")
            print(f"   错误：{r['error']}")

    print()
    print(f"总日期：{len(results)}")
    print(f"成功生成：{len(succeeded)}")
    print(f"已存在跳过：{len(skipped)}")
    print(f"失败：{len(failed)}")

    if failed:
        print()
        print("失败日期（直接重跑同一命令即可补上）：")
        for r in failed:
            print(f"  - {r['date']}")

    print("=" * 70)

    return results


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    batch_daily_flow(
        start_date=date(2026, 8, 15),
        # end_date=date.today() - timedelta(days=1),
        end_date=date(2026, 8, 31),

        # 建议先从 2 开始
        max_concurrency=2,

        # True = 已有日报也重新生成
        force=False,
    )