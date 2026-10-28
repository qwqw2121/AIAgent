# pipeline/quality.py
"""日报质量检查：事件内聚度 + 领域相关性。只记录和告警，不修改、不删除日报。"""
import json
import os
import re
import sys
from datetime import datetime, timezone

import numpy as np
from langchain_openai import ChatOpenAI

from storage.db import get_connection, fetch_report_by_date, fetch_news_by_ids

# 阈值只是起点，必须用历史日报校准（见第 4 节）
COHESION_MIN = float(os.getenv("QUALITY_COHESION_MIN", "0.55"))   # 事件平均内聚度下限
OUTLIER_MIN = float(os.getenv("QUALITY_OUTLIER_MIN", "0.45"))     # 单条新闻到事件中心的相似度下限
SCORE_MIN = int(os.getenv("QUALITY_SCORE_MIN", "3"))              # LLM 评分低于它就标记
MAX_LLM_EVENTS = int(os.getenv("QUALITY_MAX_LLM_EVENTS", "20"))   # 单次最多评审多少个事件
DOMAIN = "人工智能（大模型、机器学习、强化学习、AI 芯片与算力、AI 应用与产业动态）"

DDL = """
CREATE TABLE IF NOT EXISTS report_quality (
    report_date      TEXT PRIMARY KEY,
    checked_at       TEXT,
    event_count      INTEGER,
    flagged_events   INTEGER,
    irrelevant_news  INTEGER,
    status           TEXT,      -- ok / warn
    issues_json      TEXT
);
CREATE TABLE IF NOT EXISTS event_quality (
    report_date  TEXT,
    event_idx    INTEGER,
    event_title  TEXT,
    news_count   INTEGER,
    cohesion     REAL,
    min_sim      REAL,
    llm_score    INTEGER,
    outlier_ids  TEXT,
    reason       TEXT,
    flagged      INTEGER,
    PRIMARY KEY (report_date, event_idx)
);
"""

_judge = None


def _get_judge():
    global _judge
    if _judge is None:
        _judge = ChatOpenAI(
            model=os.getenv("JUDGE_MODEL") or os.getenv("LLM_MODEL"),
            openai_api_key=os.getenv("LLM_API_KEY"),
            base_url=os.getenv("LLM_BASE_URL"),
            temperature=0, timeout=40, max_retries=1,
            extra_body={"enable_thinking": False},
        )
    return _judge


def _json_from(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    return json.loads(m.group(0) if m else text)


def _brief(row) -> str:
    r = dict(row)
    title = (r.get("title") or "").strip()
    summary = (r.get("summary") or "").replace("\n", " ").strip()[:120]
    return f"{title}｜{summary}" if summary else title


# ---------- 第一层：向量内聚度 ----------
def _embeddings(ids) -> dict:
    """直接取 Chroma 里已有的向量，不再调用 embedding 接口"""
    from storage.vectorstore import vectorstore
    res = vectorstore._collection.get(ids=[str(i) for i in ids], include=["embeddings"])
    out = {}
    for _id, emb in zip(res["ids"], res["embeddings"]):
        if emb is not None:
            out[int(_id)] = np.asarray(emb, dtype=float)
    return out


def cohesion_stats(ids, embs) -> dict | None:
    items = [(i, embs[i]) for i in ids if i in embs]
    if len(items) < 2:
        return None
    M = np.stack([v for _, v in items])
    M = M / np.linalg.norm(M, axis=1, keepdims=True)
    center = M.mean(axis=0)
    center /= np.linalg.norm(center)
    sims = M @ center
    pair = M @ M.T
    iu = np.triu_indices(len(items), 1)
    return {
        "cohesion": float(sims.mean()),
        "min_sim": float(pair[iu].min()),
        "outliers": [items[k][0] for k, s in enumerate(sims) if s < OUTLIER_MIN],
    }


# ---------- 第二层：LLM 评审 ----------
EVENT_PROMPT = """你在检查一份新闻日报里的“事件合并”是否合理。
规则：同一事件 = 同一件具体的事（同一次发布、同一个公司动作、同一起事件）。
仅仅主题相近（例如都与“大模型”有关）不算同一事件。
只依据下面给出的内容判断，只输出 JSON，不要多余文字：
{{"score": 1到5的整数, "off_topic_ids": [不属于该事件的新闻id], "reason": "一句话说明"}}
评分：5=完全同一事件；3=相关但松散；1=明显把不相关的新闻合并在一起。

【事件标题】{title}
【事件摘要】{summary}
【合并的新闻】
{news}"""

RELEVANCE_PROMPT = """领域定义：{domain}。
下面是一批新闻，找出其中【与该领域无关】的新闻。
只输出 JSON：{{"irrelevant_ids": [id, ...]}}，没有就返回空数组。

{news}"""


def judge_event(event: dict, news_map: dict) -> dict | None:
    ids = [i for i in event.get("news_ids", []) if i in news_map]
    lines = "\n".join(f"[{i}] {_brief(news_map[i])}" for i in ids)
    prompt = EVENT_PROMPT.format(
        title=event.get("title", ""),
        summary=(event.get("summary") or "")[:300],
        news=lines,
    )
    try:
        data = _json_from(_get_judge().invoke(prompt).content)
        return {
            "score": int(data.get("score", 0)) or None,
            "off_topic_ids": [int(x) for x in data.get("off_topic_ids", []) if str(x).lstrip("-").isdigit()],
            "reason": str(data.get("reason", ""))[:200],
        }
    except Exception as e:
        print(f"⚠️ 事件评审失败: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def find_irrelevant(news_map: dict, chunk: int = 40) -> list[int]:
    ids = list(news_map)
    bad: list[int] = []
    for s in range(0, len(ids), chunk):
        part = ids[s:s + chunk]
        lines = "\n".join(f"[{i}] {_brief(news_map[i])}" for i in part)
        try:
            data = _json_from(_get_judge().invoke(RELEVANCE_PROMPT.format(domain=DOMAIN, news=lines)).content)
            bad += [int(x) for x in data.get("irrelevant_ids", []) if int(x) in news_map]
        except Exception as e:
            print(f"⚠️ 相关性评审失败: {type(e).__name__}: {e}", file=sys.stderr)
    return bad


# ---------- 主流程 ----------
def run_quality_check(report_date: str) -> dict:
    conn = get_connection()
    try:
        conn.executescript(DDL)
        row = fetch_report_by_date(conn, report_date)
        if not row:
            return {"date": report_date, "status": "skip", "reason": "无日报"}

        events = json.loads(row["report_json"]).get("events") or []
        all_ids = {i for e in events for i in e.get("news_ids", []) if isinstance(i, int)}
        news_map = dict(fetch_news_by_ids(conn, all_ids)) if all_ids else {}
        try:
            embs = _embeddings(all_ids) if all_ids else {}
        except Exception as e:
            print(f"⚠️ 读取向量失败，跳过内聚度: {e}", file=sys.stderr)
            embs = {}

        issues, flagged_count, llm_used = [], 0, 0
        conn.execute("DELETE FROM event_quality WHERE report_date = ?", (report_date,))

        for idx, e in enumerate(events, 1):
            ids = [i for i in e.get("news_ids", []) if i in news_map]
            stats = cohesion_stats(ids, embs)
            verdict = None
            if len(ids) >= 2 and llm_used < MAX_LLM_EVENTS:
                verdict = judge_event(e, news_map)
                llm_used += 1

            outliers = set(stats["outliers"]) if stats else set()
            if verdict:
                outliers |= set(verdict["off_topic_ids"])

            reasons = []
            if stats and stats["cohesion"] < COHESION_MIN:
                reasons.append(f"内聚度 {stats['cohesion']:.2f} 低于 {COHESION_MIN}")
            if verdict and verdict["score"] and verdict["score"] < SCORE_MIN:
                reasons.append(f"评审 {verdict['score']} 分：{verdict['reason']}")
            if outliers:
                reasons.append(f"疑似误并的新闻: {sorted(outliers)}")
            flagged = int(bool(reasons))
            flagged_count += flagged
            if flagged:
                issues.append({"event_idx": idx, "title": e.get("title", ""), "reasons": reasons})

            conn.execute(
                "INSERT OR REPLACE INTO event_quality VALUES (?,?,?,?,?,?,?,?,?,?)",
                (report_date, idx, e.get("title", ""), len(ids),
                 stats["cohesion"] if stats else None,
                 stats["min_sim"] if stats else None,
                 verdict["score"] if verdict else None,
                 json.dumps(sorted(outliers)),
                 "；".join(reasons), flagged),
            )

        irrelevant = find_irrelevant(news_map) if news_map else []
        if irrelevant:
            issues.append({"event_idx": None, "title": "领域不相关的新闻",
                           "reasons": [f"{i}: {_brief(news_map[i])[:60]}" for i in irrelevant]})

        status = "warn" if (flagged_count or irrelevant) else "ok"
        conn.execute(
            "INSERT OR REPLACE INTO report_quality VALUES (?,?,?,?,?,?,?)",
            (report_date, datetime.now(timezone.utc).isoformat(timespec="seconds"),
             len(events), flagged_count, len(irrelevant), status,
             json.dumps(issues, ensure_ascii=False)),
        )
        conn.commit()
        return {"date": report_date, "status": status, "events": len(events),
                "flagged": flagged_count, "irrelevant": len(irrelevant), "issues": issues}
    finally:
        conn.close()


if __name__ == "__main__":
    # 用法：python -m pipeline.quality 2026-10-26
    d = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone.utc).date().isoformat()
    result = run_quality_check(d)
    print(json.dumps(result, ensure_ascii=False, indent=2))