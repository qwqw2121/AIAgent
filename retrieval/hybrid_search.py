"""
统一检索流程：

关键词召回 + 向量召回
    -> RRF 融合
    -> SQLite 回表
    -> 时间过滤
    -> 重要性过滤
    -> 可选重排

支持自适应时间范围：用户指定范围 -> 30 天 -> 90 天
扩展检索结果会标记 time_scope。
"""

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import os
import sys
import time

from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

from retrieval.query_parser import parse_query
from retrieval.keyword_search import keyword_search
from retrieval.vector_search import vector_search
from retrieval.fusion import rrf_fuse
from retrieval import reranker

from storage.db import get_connection, fetch_news_by_ids


MAX_LIMIT = 8
SNIPPET_CHARS = 200

RECALL_MULT = int(os.getenv("HYBRID_RECALL_MULT", "3"))
RRF_K = int(os.getenv("HYBRID_RRF_K", "60"))
RERANK_CANDIDATES = int(os.getenv("HYBRID_RERANK_CANDIDATES", "20"))

CHANNEL_WEIGHTS = {"keyword": 1.5, "vector": 1.0}

# 自适应时间范围
EXPAND_DAYS = (30, 90)

TIMEZONE = ZoneInfo("Asia/Shanghai")


def _snippet(text, n: int = SNIPPET_CHARS) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "…"


def _safe_result(future, label: str) -> list[dict]:
    """取并行召回结果，异常时打印并返回空列表，避免单路失败拖垮整体。"""
    try:
        return future.result()
    except Exception as e:
        print(f"⚠️ {label}召回异常: {e}", file=sys.stderr)
        return []


def _apply_filters(
    items: list[dict],
    start_ts: int | None,
    end_ts: int | None,
    min_importance: int | None,
) -> list[dict]:
    """统一时间过滤 + 重要性过滤。"""
    items = _filter_by_time(items, start_ts, end_ts)
    if min_importance is not None:
        items = [i for i in items if (i.get("importance") or 0) >= min_importance]
    return items


def _enrich(items: list[dict], category: str | None) -> list[dict]:
    """根据 news_id 回查 SQLite，补全新闻信息。"""

    ids = [i["news_id"] for i in items if isinstance(i.get("news_id"), int)]

    rows = {}
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
        # 避免修改召回阶段的原始对象
        it = dict(it)

        nid = it.get("news_id")
        row = rows.get(nid)

        # 回表成功但找不到对应新闻，丢弃
        if row is None and lookup_ok and isinstance(nid, int):
            continue

        if row is not None:
            it["title"] = row.get("title") or it.get("title")
            it["source"] = row.get("source") or it.get("source")
            it["url"] = row.get("url") or it.get("url")
            it["published"] = row.get("published") or it.get("published")
            it["published_ts"] = row.get("published_ts")
            it["summary"] = row.get("summary") or it.get("summary")
            it["category"] = row.get("llm_category")
            it["importance"] = row.get("importance")

        # 分类严格过滤
        if category and it.get("category") != category:
            continue

        it["_text"] = (
            f"{it.get('title') or ''}\n"
            f"{it.get('summary') or ''}"
        ).strip()

        out.append(it)

    return out


def _filter_by_time(
    items: list[dict],
    start_ts: int | None,
    end_ts: int | None,
) -> list[dict]:
    """按发布时间过滤，采用左闭右开区间。"""

    if start_ts is None and end_ts is None:
        return items

    results = []

    for item in items:
        ts = item.get("published_ts")

        # 有时间条件时，不允许发布时间缺失的记录通过
        if ts is None:
            continue

        try:
            ts = int(ts)
        except (TypeError, ValueError):
            continue

        if start_ts is not None and ts < start_ts:
            continue
        if end_ts is not None and ts >= end_ts:
            continue

        results.append(item)

    return results


def _format(item: dict) -> dict:
    """统一对外返回字段。"""

    return {
        "news_id": item.get("news_id"),
        "title": item.get("title") or "未知标题",
        "source": item.get("source") or "未知来源",
        "url": item.get("url"),
        "published": item.get("published"),
        "category": item.get("category"),
        "importance": item.get("importance"),
        "summary": _snippet(item.get("summary")),

        # requested：用户指定时间范围内
        # expanded_30d / expanded_90d：扩展时间范围补充
        "time_scope": item.get("time_scope", "unrestricted"),
    }


def _search_once(
    search_query: str,
    category: str | None,
    limit: int,
    min_importance: int | None,
    start_ts: int | None,
    end_ts: int | None,
) -> list[dict]:
    """
    执行单次检索：
    并行召回 -> RRF -> 回表 -> 时间过滤 -> 重要性过滤。
    """

    recall_k = max(limit * RECALL_MULT, 10)
    if start_ts is not None or end_ts is not None:
        recall_k = max(recall_k * 5, 50)

    # 没有关键词时，直接通过 SQLite 按时间查询
    if not search_query:
        rows = keyword_search(
            None,
            category=category,
            limit=recall_k,
            min_importance=min_importance,
            start_ts=start_ts,
            end_ts=end_ts,
        )
        enriched = _enrich(rows, category)
        return _apply_filters(enriched, start_ts, end_ts, min_importance)

    # 并行关键词召回和向量召回
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_kw = pool.submit(
            keyword_search,
            query=search_query,
            category=category,
            limit=recall_k,
            min_importance=min_importance,
            start_ts=start_ts,
            end_ts=end_ts,
        )
        f_vec = pool.submit(
            vector_search,
            query=search_query,
            top_k=recall_k,
            start_ts=start_ts,
            end_ts=end_ts,
        )
        kw_hits = _safe_result(f_kw, "关键词")
        vec_hits = _safe_result(f_vec, "向量")

    # RRF 融合
    fused = rrf_fuse(
        {"keyword": kw_hits, "vector": vec_hits},
        k=RRF_K,
        weights=CHANNEL_WEIGHTS,
    )

    # 关键词召回结果优先进入精排候选
    kw_ids = {item.get("news_id") for item in kw_hits}
    for item in fused:
        item["_keyword_match"] = item.get("news_id") in kw_ids

    fused.sort(
        key=lambda x: (x.get("_keyword_match", False), x.get("rrf_score", 0)),
        reverse=True,
    )

    enriched = _enrich(fused, category)
    candidates = _apply_filters(enriched, start_ts, end_ts, min_importance)

    print(
        f"🔎 recall query={search_query!r} "
        f"kw={len(kw_hits)} vec={len(vec_hits)} "
        f"fused={len(fused)} enriched={len(candidates)}",
        file=sys.stderr,
    )

    return candidates


def hybrid_search(
    query: str | None = None,
    category: str | None = None,
    limit: int = 5,
    min_importance: int | None = None,
    use_rerank: bool = True,
) -> list[dict]:

    t0 = time.perf_counter()

    limit = max(1, min(limit, MAX_LIMIT))

    # 1. 解析自然语言查询
    parsed = parse_query(query or "")

    search_query = parsed["query"]
    requested_start = parsed["start_ts"]
    requested_end = parsed["end_ts"]

    has_time_filter = (
        requested_start is not None
        or requested_end is not None
    )

    print(
        f"🔎 parsed query={search_query!r} "
        f"start={requested_start} end={requested_end}",
        file=sys.stderr,
    )

    # 2. 首先执行用户指定的时间范围
    candidates = _search_once(
        search_query=search_query,
        category=category,
        limit=limit,
        min_importance=min_importance,
        start_ts=requested_start,
        end_ts=requested_end,
    )

    # 指定范围内的新闻优先保留
    for item in candidates:
        item["time_scope"] = "requested"

    print(f"🔎 requested range: {len(candidates)} 条", file=sys.stderr)

    # 3. 如果结果不足，逐步扩大时间范围
    if has_time_filter and len(candidates) < limit:

        now_ts = int(datetime.now(TIMEZONE).timestamp())
        seen_ids = {item.get("news_id") for item in candidates}

        for days in EXPAND_DAYS:

            # 扩展后的起始时间
            expanded_start = now_ts - days * 86400
            # 如果用户指定了结束时间，沿用用户的结束时间
            expanded_end = requested_end or now_ts

            # 如果扩展范围没有比原范围更大，就跳过
            if requested_start is not None and expanded_start >= requested_start:
                continue

            expanded = _search_once(
                search_query=search_query,
                category=category,
                limit=limit,
                min_importance=min_importance,
                start_ts=expanded_start,
                end_ts=expanded_end,
            )

            added = 0
            for item in expanded:
                nid = item.get("news_id")
                if nid in seen_ids:
                    continue
                item["time_scope"] = f"expanded_{days}d"
                candidates.append(item)
                seen_ids.add(nid)
                added += 1

            print(
                f"🔎 expanded {days}d: found={len(expanded)} added={added}",
                file=sys.stderr,
            )

            if len(candidates) >= limit:
                break

    # 4. 截取精排候选
    pool_n = max(RERANK_CANDIDATES, limit)
    candidates = candidates[:pool_n]

    # 5. 可选重排
    if use_rerank and reranker.is_enabled():
        final = reranker.rerank(search_query, candidates, top_n=limit)
    else:
        final = candidates[:limit]

    # 精排会保留原 item 的 time_scope；这里只兜底缺失的情况
    for item in final:
        item.setdefault("time_scope", "requested")

    print(
        f"🔎 hybrid '{search_query}' "
        f"time_filter={has_time_filter} "
        f"results={len(final)} "
        f"scopes={[r.get('time_scope') for r in final]} "
        f"(total {time.perf_counter() - t0:.2f}s)",
        file=sys.stderr,
    )

    return [_format(r) for r in final]


def warmup() -> None:
    """MCP 启动预热：向量库 + 重排模型。"""

    t0 = time.perf_counter()

    try:
        vector_search("warm up", top_k=1)
        print(f"✅ 向量库预热完成 {time.perf_counter() - t0:.1f}s", file=sys.stderr)
    except Exception as e:
        print(f"⚠️ 预热失败: {e}", file=sys.stderr)

    reranker.warmup()