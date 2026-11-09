# retrieval/keyword_search.py
"""
关键词召回：调用现有 SQLite 查询（storage.db.query_news）。

query_news 只支持单个 LIKE 子串，自然语言问题整句几乎匹配不到，
所以这里先拆成若干检索词，分别查询，再按“命中词数 + 标题命中”排序。
"""
import re
import sys

from storage.db import get_connection, query_news

# 口语化填充词，拆词前去掉
_FILLERS = (
    "相关新闻", "有关", "关于", "相关", "新闻", "最新", "最近",
    "帮我", "请问", "查找", "搜索", "一下", "的",
)
_SPLIT_RE = re.compile(r"[\s,，、;；|/]+")


def extract_terms(query: str, max_terms: int = 5) -> list[str]:
    """把查询拆成检索词：整句（去填充词后）优先，其后是按空白/标点拆出的子词"""
    q = (query or "").strip()
    if not q:
        return []
    cleaned = q
    for f in _FILLERS:
        cleaned = cleaned.replace(f, " ")
    parts = [p for p in _SPLIT_RE.split(cleaned) if p]

    terms: list[str] = []
    whole = "".join(parts) if len(parts) == 1 else cleaned.strip()
    for t in [whole, *parts]:
        t = t.strip()
        if t and t not in terms:
            terms.append(t)
    return terms[:max_terms] or [q]


def _normalize(row: dict) -> dict:
    """统一字段名，和 vector_search 的输出保持一致"""
    return {
        "news_id": row.get("id"),
        "title": row.get("title"),
        "source": row.get("source"),
        "url": row.get("url"),
        "published": row.get("published"),
        "published_ts": row.get("published_ts"),
        "summary": row.get("summary"),
        "category": row.get("llm_category"),
        "importance": row.get("importance"),
        "keywords": row.get("keywords"),
    }


def keyword_search(
    query: str | None = None,
    category: str | None = None,
    limit: int = 20,
    min_importance: int | None = None,
    start_ts: int | None = None,
    end_ts: int | None = None,
) -> list[dict]:

    conn = get_connection()

    try:
        terms = extract_terms(query) if query else []

        if not terms:
            rows = query_news(
                conn,
                category=category,
                min_importance=min_importance,
                limit=limit,
                start_ts=start_ts,
                end_ts=end_ts,
            )

            return [_normalize(r) for r in rows]

        merged = {}
        scores = {}

        for idx, term in enumerate(terms):

            rows = query_news(
                conn,
                category=category,
                keyword=term,
                min_importance=min_importance,
                limit=limit,
                start_ts=start_ts,
                end_ts=end_ts,
            )

            weight = 2.0 if idx == 0 else 1.0

            for r in rows:
                nid = r["id"]

                merged.setdefault(nid, r)
                scores[nid] = scores.get(nid, 0.0) + weight

                if term.lower() in (r.get("title") or "").lower():
                    scores[nid] += 0.5

    except Exception as e:
        print(
            f"⚠️ keyword_search 失败: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return []

    finally:
        conn.close()

    ranked = sorted(
        merged.values(),
        key=lambda r: (
            scores[r["id"]],
            r.get("published_ts") or 0,
        ),
        reverse=True,
    )

    return [_normalize(r) for r in ranked[:limit]]