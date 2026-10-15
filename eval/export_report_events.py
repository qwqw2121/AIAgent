# eval/export_report_events.py
"""
导出「日报关键事件」供人工标注。
简历里的 147 个事件来自 daily_reports.report_json，而不是 events（聚类）表。

用法:
  python eval/export_report_events.py              # 近 30 天随机导出 100 条
  python eval/export_report_events.py -n 147 -d 30 # 全量标注
标注完成后沿用:
  python eval/run_eval.py score eval/label_report.csv

标注口径（label 列填 1 / 0）:
  1 = 摘要与来源新闻一致，无编造；合并的新闻确属同一事件
  0 = 编造 / 与来源不符 / 把不同事件合并 / 来源缺失
note 列建议填错误类别：编造、与来源不符、错误合并、来源缺失、粒度过泛
"""
import argparse
import csv
import json
import os
import random
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from storage.db import get_connection  # noqa: E402


def main(n, days, out):
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_connection()
    items = []
    try:
        reports = conn.execute(
            "SELECT report_date, report_json FROM daily_reports "
            "WHERE report_date >= ? ORDER BY report_date", (since,)
        ).fetchall()
        for r in reports:
            try:
                rep = json.loads(r[1])
            except Exception:
                continue
            for e in rep.get("events", []):
                ids = [int(i) for i in e.get("news_ids", []) if str(i).isdigit()]
                src = ""
                if ids:
                    ph = ",".join("?" * len(ids))
                    rows = conn.execute(
                        f"SELECT title, summary FROM news WHERE id IN ({ph})", ids
                    ).fetchall()
                    src = " || ".join(f"{x[0]}：{(x[1] or '')[:120]}" for x in rows)
                items.append([r[0], e.get("title", ""), e.get("summary", ""), src])
    finally:
        conn.close()

    random.seed(42)  # 固定种子，保证可复现
    sample = random.sample(items, min(n, len(items)))
    sample.sort(key=lambda x: x[0])

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["report_date", "title", "summary", "sources", "label(1对/0错)", "note"])
        for it in sample:
            w.writerow([*it, "", ""])
    print(f"✅ 近 {days} 天共 {len(items)} 个日报事件，已导出 {len(sample)} 条 → {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("-d", type=int, default=30)
    ap.add_argument("-o", default="eval/label_report.csv")
    a = ap.parse_args()
    main(a.n, a.d, a.o)