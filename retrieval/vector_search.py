# retrieval/vector_search.py
"""
向量召回：调用现有 Chroma 向量检索（storage.vectorstore）。
vectorstore 在首次调用时才导入，导入失败（如缺 API Key）只影响这一路召回。
"""
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


def vector_search(query: str, top_k: int = 20,
                  min_similarity: float | None = None) -> list[dict]:
    """
    返回按相似度降序的新闻列表（已统一字段）。
    集合使用 cosine 距离，similarity = 1 - distance。
    """
    if not (query or "").strip():
        return []
    try:
        pairs = _get_vectorstore().similarity_search_with_score(query, k=top_k)
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
            "published": meta.get("published") or meta.get("published_at") or meta.get("date"),
            "summary": doc.page_content,
            "similarity": round(similarity, 4),
        })

    if not results:
        print("⚠️ 向量库检索无结果，请检查向量库是否有数据", file=sys.stderr)
    return results