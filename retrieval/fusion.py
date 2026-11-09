# retrieval/fusion.py
"""RRF（Reciprocal Rank Fusion）排名融合：只看名次，不受各路分数量纲影响。"""


def candidate_key(item: dict) -> str | None:
    nid = item.get("news_id")

    if nid not in (None, ""):
        try:
            return f"news_id:{int(nid)}"
        except (TypeError, ValueError):
            pass

    for field in ("url", "title"):
        v = item.get(field)

        if v not in (None, ""):
            return f"{field}:{str(v).strip().lower()}"

    return None


def rrf_fuse(
    rank_lists: dict[str, list[dict]],
    k: int = 60,
    weights: dict[str, float] | None = None,
    top_n: int | None = None,
) -> list[dict]:
    """
    rank_lists: {"keyword": [...], "vector": [...]}，每个列表已按相关度降序
    score(d) = Σ weight_c / (k + rank_c(d))，rank 从 1 开始

    返回融合后的 dict 列表，附加字段：
      rrf_score  融合分
      channels   命中的召回通道
      ranks      各通道名次
    字段合并：以先出现的为准，缺失字段由其他通道补齐。
    """
    weights = weights or {}
    merged: dict[str, dict] = {}

    for channel, items in rank_lists.items():
        w = weights.get(channel, 1.0)
        for rank, item in enumerate(items, start=1):
            key = candidate_key(item)
            if key is None:
                continue
            entry = merged.get(key)
            if entry is None:
                entry = dict(item)
                entry["rrf_score"] = 0.0
                entry["channels"] = []
                entry["ranks"] = {}
                merged[key] = entry
            else:
                for f, v in item.items():
                    if entry.get(f) in (None, "") and v not in (None, ""):
                        entry[f] = v
            entry["rrf_score"] += w / (k + rank)
            entry["channels"].append(channel)
            entry["ranks"][channel] = rank

    fused = sorted(merged.values(), key=lambda e: e["rrf_score"], reverse=True)
    for e in fused:
        e["rrf_score"] = round(e["rrf_score"], 6)
    return fused[:top_n] if top_n else fused