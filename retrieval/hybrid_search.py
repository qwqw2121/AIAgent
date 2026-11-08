# retrieval/hybrid_search.py
"""
统一检索流程：并行召回(关键词+向量) → RRF 融合 → 回表补全/过滤 → 可选重排 → 统一返回
"""

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from storage.db import get_connection, fetch_news_by_ids

from retrieval.keyword_search import keyword_search
from retrieval.vector_search import vector_search
from retrieval.fusion import rrf_fuse
from retrieval import reranker

MAX_LIMIT = 8
SNIPPET_CHARS = 200

RECALL_MULT = int(os.getenv("HYBRID_RECALL_MULT", "3"))          # 每路召回 = limit * 倍数
RRF_K = int(os.getenv("HYBRID_RRF_K", "60"))
RERANK_CANDIDATES = int(os.getenv("HYBRID_RERANK_CANDIDATES", "20"))
CHANNEL_WEIGHTS = {"keyword": 0.8, "vector": 1.0}


def _snippet(text, n: int = SNIPPET_CHARS) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "…"


def _enrich(items: list[dict], category: str | None) -> list[dict]:
    """
    以 SQLite 为准回表：补全字段、剔除向量库里已不存在的脏数据、应用分类过滤。
    回表失败则保持原样。
    """
    ids = [i["news_id"] for i in items if isinstance(i.get("news_id"), int)]
    rows: dict = {}
    lookup_ok = False
    if ids:
        conn = get_connection()
        try:
            rows = fetch_news_by_ids(conn, ids)
            lookup_ok = True
        except Exception as e:
            print(f"⚠️ 回表失败: {type(e).__name__}: {e}", file=sys.stderr)
        finally:
            conn.close()

    out = []
    for it in items:
        nid = it.get("news_id")
        row = rows.get(nid)
        if row is None and lookup_ok and isinstance(nid, int):
            continue  # 向量库有、数据库没有：丢弃
        if row is not None:
            it["title"] = row.get("title") or it.get("title")
            it["source"] = row.get("source") or it.get("source")
            it["url"] = row.get("url") or it.get("url")
            it["published"] = row.get("published") or it.get("published")
            it["summary"] = row.get("summary") or it.get("summary")
            it["category"] = row.get("llm_category") or it.get("category")
            it["importance"] = row.get("importance", it.get("importance"))
        if category and it.get("category") and it["category"] != category:
            continue
        it["_text"] = f"{it.get('title') or ''}\n{it.get('summary') or ''}".strip()
        out.append(it)
    return out


def _format(item: dict) -> dict:
    """对外输出：精简字段，摘要截断，节省 LLM 上下文"""
    score = item.get("rerank_score", item.get("rrf_score"))
    return {
        "news_id": item.get("news_id"),
        "title": item.get("title") or "未知标题",
        "source": item.get("source") or "未知来源",
        "url": item.get("url"),
        "published": item.get("published"),
        "category": item.get("category"),
        "importance": item.get("importance"),
        "summary": _snippet(item.get("summary")),
        # "score": score,
        # "channels": item.get("channels", []),
    }


def hybrid_search(
    query: str | None = None,
    category: str | None = None,
    limit: int = 5,
    min_importance: int | None = None,
    use_rerank: bool = True,
) -> list[dict]:
    t0 = time.perf_counter()
    limit = max(1, min(limit, MAX_LIMIT))
    recall_k = max(limit * RECALL_MULT, 10)

    # 没有查询词：退化为分类/时间浏览（只走 SQL）
    if not (query or "").strip():
        rows = keyword_search(None, category=category, limit=limit,
                              min_importance=min_importance)
        return [_format(r) for r in _enrich(rows, category)]

    # 1) 并行召回，单路失败不影响另一路
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_kw = pool.submit(keyword_search, query, category, recall_k, min_importance)
        f_vec = pool.submit(vector_search, query, recall_k)
        try:
            kw_hits = f_kw.result()
        except Exception as e:
            print(f"⚠️ 关键词召回异常: {e}", file=sys.stderr)
            kw_hits = []
        try:
            vec_hits = f_vec.result()
        except Exception as e:
            print(f"⚠️ 向量召回异常: {e}", file=sys.stderr)
            vec_hits = []
    t_recall = time.perf_counter() - t0

    # 2) RRF 融合
    fused = rrf_fuse({"keyword": kw_hits, "vector": vec_hits},
                     k=RRF_K, weights=CHANNEL_WEIGHTS)

    # 3) 回表补全 / 过滤（向量结果的 importance 过滤也在这里做）
    candidates = _enrich(fused, category)
    if min_importance is not None:
        candidates = [c for c in candidates
                      if (c.get("importance") or 0) >= min_importance]

    # 4) 可选重排：只对前 N 个候选精排
    pool_n = max(RERANK_CANDIDATES, limit)
    candidates = candidates[:pool_n]
    if use_rerank and reranker.is_enabled():
        final = reranker.rerank(query, candidates, top_n=limit)
    else:
        final = candidates[:limit]

    print(
        f"🔎 hybrid '{query}' kw={len(kw_hits)} vec={len(vec_hits)} "
        f"fused={len(fused)} -> {len(final)} 条 "
        f"(recall {t_recall:.2f}s, total {time.perf_counter() - t0:.2f}s)",
        file=sys.stderr,
    )
    return [_format(r) for r in final]


def warmup() -> None:
    """MCP 启动预热：向量库 + 重排模型"""
    t0 = time.perf_counter()
    try:
        vector_search("warm up", top_k=1)
        print(f"✅ 向量库预热完成 {time.perf_counter() - t0:.1f}s", file=sys.stderr)
    except Exception as e:
        print(f"⚠️ 预热失败: {e}", file=sys.stderr)
    reranker.warmup()