# pipeline/quality.py
"""
日报质量检查（无 LLM、无新表，只告警不改数据）：
1. 事件内聚度：用事件的全部新闻向量评估聚类是否合理，用来校准聚类阈值
2. 数字溯源：日报总结里出现的数字必须能在来源新闻里找到，防止编造
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

import numpy as np

from storage.db import get_connection
from embedding.vector_store import get_vector_store

COHESION_MIN = float(os.getenv("QUALITY_COHESION_MIN", "0.55"))  # 事件平均内聚度下限
OUTLIER_MIN = float(os.getenv("QUALITY_OUTLIER_MIN", "0.45"))    # 单条新闻到事件中心的相似度下限

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(text: str) -> set[str]:
    """提取数字，去掉千分位逗号，忽略单个字符的数字（如 '3 个'，易与中文数字互换）"""
    out = set()
    for m in _NUM_RE.findall(text or ""):
        m = m.replace(",", "")
        if len(m) >= 2:
            out.add(m)
    return out


def cohesion_stats(ids, embs: dict) -> dict | None:
    items = [(i, np.asarray(embs[i], dtype=float)) for i in ids if i in embs]
    if len(items) < 2:
        return None
    M = np.stack([v for _, v in items])
    M = M / np.linalg.norm(M, axis=1, keepdims=True)
    center = M.mean(axis=0)
    center /= np.linalg.norm(center)
    sims = M @ center
    return {
        "cohesion": float(sims.mean()),
        "outliers": [items[k][0] for k, s in enumerate(sims) if s < OUTLIER_MIN],
    }


def run_quality_check(report_date: str) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT report_json FROM daily_reports WHERE report_date = ?",
            (report_date,),
        ).fetchone()
        if not row or not row[0]:
            return {"date": report_date, "status": "skip", "reason": "无日报"}

        events = json.loads(row[0]).get("events") or []
        store = get_vector_store()
        issues = []
        flagged = 0

        for idx, ev in enumerate(events, 1):
            event_id = ev.get("event_id")
            if event_id is None:
                continue

            # 事件的全部新闻（不是日报里挑出来的那几条）
            news_rows = conn.execute("""
                SELECT n.id, n.title, n.summary
                FROM event_news en JOIN news n ON n.id = en.news_id
                WHERE en.event_id = ?
            """, (event_id,)).fetchall()
            news_ids = [r[0] for r in news_rows]
            source_text = " ".join(f"{r[1] or ''} {r[2] or ''}" for r in news_rows)

            reasons = []

            # 1) 内聚度
            try:
                embs = store.get_embeddings(news_ids)
            except Exception as e:
                embs = {}
                print(f"⚠️ 读取向量失败 event_id={event_id}: {e}", file=sys.stderr)
            stats = cohesion_stats(news_ids, embs)
            if stats and stats["cohesion"] < COHESION_MIN:
                reasons.append(f"内聚度 {stats['cohesion']:.2f} < {COHESION_MIN}")
            if stats and stats["outliers"]:
                reasons.append(f"疑似误并新闻: {sorted(stats['outliers'])}")

            # 2) 数字溯源
            claimed = _numbers(f"{ev.get('title', '')} {ev.get('summary', '')} {ev.get('why_it_matters', '')}")
            unsupported = sorted(claimed - _numbers(source_text))
            if unsupported:
                reasons.append(f"数字在来源新闻中找不到: {unsupported}")

            if reasons:
                flagged += 1
                issues.append({"event_idx": idx, "title": ev.get("title", ""), "reasons": reasons})

        status = "warn" if flagged else "ok"
        return {
            "date": report_date,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": status,
            "events": len(events),
            "flagged": flagged,
            "issues": issues,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    # 用法：python -m pipeline.quality 2026-10-26
    d = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone.utc).date().isoformat()
    print(json.dumps(run_quality_check(d), ensure_ascii=False, indent=2))