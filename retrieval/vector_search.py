import sys

_vs = None


def _get_vectorstore():
    global _vs
    if _vs is None:
        from storage.vectorstore import vectorstore
        _vs = vectorstore
    return _vs


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def _build_time_filter(start_ts, end_ts):
    """把 start/end 时间戳转成 vectorstore 的 filter 条件，无时间条件返回 None。"""
    if start_ts is None and end_ts is None:
        return None
    conds = []
    if start_ts is not None:
        conds.append({"published_ts": {"$gte": int(start_ts)}})
    if end_ts is not None:
        conds.append({"published_ts": {"$lt": int(end_ts)}})
    return conds[0] if len(conds) == 1 else {"$and": conds}


def vector_search(
    query: str,
    top_k: int = 20,
    min_similarity: float | None = None,
    start_ts: int | None = None,
    end_ts: int | None = None,
) -> list[dict]:
    if not (query or "").strip():
        return []

    try:
        store = _get_vectorstore()
        kwargs = {"query": query, "k": top_k}
        where = _build_time_filter(start_ts, end_ts)
        if where:
            kwargs["filter"] = where
        pairs = store.similarity_search_with_score(**kwargs)
    except Exception as e:
        print(f"⚠️ vector_search 失败: {type(e).__name__}: {e}", file=sys.stderr)
        return []

    results = []
    for doc, distance in pairs:
        meta = doc.metadata or {}
        similarity = 1.0 - float(distance)
        if min_similarity is not None and similarity < min_similarity:
            continue

        news_id = meta.get("news_id") or meta.get("id") or getattr(doc, "id", None)
        results.append({
            "news_id": _to_int(news_id),
            "title": meta.get("title"),
            "source": meta.get("source"),
            "url": meta.get("url") or meta.get("link"),
            "published": (
                meta.get("published")
                or meta.get("published_at")
                or meta.get("date")
            ),
            "published_ts": _to_int(meta.get("published_ts")),
            "summary": doc.page_content,
            "similarity": round(similarity, 4),
        })

    return results