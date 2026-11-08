"""
运行：pytest tests/test_retrieval.py -v
全部是离线测试：不需要 Chroma / DashScope / 网络，SQLite 用临时库。
"""
import sqlite3

import pytest

from retrieval import fusion, reranker
from retrieval import hybrid_search as hs
from retrieval.keyword_search import extract_terms, keyword_search


def item(nid, title="t", **kw):
    return {"news_id": nid, "title": f"{title}{nid}", **kw}


# ---------------- fusion ----------------
def test_rrf_consensus_beats_single_channel():
    # A: 关键词第1 + 向量第3；B: 仅向量第1。两路都命中的 A 应排第一
    kw = [item(1)]
    vec = [item(2), item(9), item(1)]
    out = fusion.rrf_fuse({"keyword": kw, "vector": vec},
                          weights={"keyword": 0.8, "vector": 1.0})
    assert [x["news_id"] for x in out][:2] == [1, 2]
    a = out[0]
    assert a["channels"] == ["keyword", "vector"]
    assert a["ranks"] == {"keyword": 1, "vector": 3}
    assert a["rrf_score"] == pytest.approx(0.8 / 61 + 1.0 / 63, abs=1e-6)


def test_rrf_dedup_and_field_merge():
    kw = [{"news_id": 1, "title": "T", "url": None}]
    vec = [{"news_id": 1, "title": None, "url": "http://x"}]
    out = fusion.rrf_fuse({"keyword": kw, "vector": vec})
    assert len(out) == 1
    assert out[0]["title"] == "T" and out[0]["url"] == "http://x"


def test_rrf_one_channel_empty_and_top_n():
    out = fusion.rrf_fuse({"keyword": [], "vector": [item(1), item(2), item(3)]}, top_n=2)
    assert [x["news_id"] for x in out] == [1, 2]


def test_rrf_weights_change_order():
    kw, vec = [item(1)], [item(2)]
    out = fusion.rrf_fuse({"keyword": kw, "vector": vec},
                          weights={"keyword": 2.0, "vector": 1.0})
    assert out[0]["news_id"] == 1


# ---------------- keyword terms ----------------
def test_extract_terms():
    assert extract_terms("强化学习相关新闻") == ["强化学习"]
    assert extract_terms("给我强化学习相关新闻") == ["强化学习"]
    assert extract_terms("OpenAI 最新 发布") == ["OpenAI 发布", "OpenAI", "发布"]
    assert extract_terms("") == []


# ---------------- reranker ----------------
def test_rerank_disabled_passthrough(monkeypatch):
    monkeypatch.setattr(reranker, "RERANK_ENABLED", False)
    cands = [item(1), item(2), item(3)]
    assert reranker.rerank("q", cands, top_n=2) == cands[:2]


def test_rerank_reorders_when_enabled(monkeypatch):
    monkeypatch.setattr(reranker, "RERANK_ENABLED", True)
    monkeypatch.setattr(reranker, "RERANK_BACKEND", "local")
    monkeypatch.setattr(reranker, "_rerank_local",
                        lambda q, docs: [(0, 0.1), (1, 0.9), (2, 0.5)])
    out = reranker.rerank("q", [item(1), item(2), item(3)], top_n=2)
    assert [x["news_id"] for x in out] == [2, 3]
    assert out[0]["rerank_score"] == 0.9


def test_rerank_failure_falls_back(monkeypatch):
    monkeypatch.setattr(reranker, "RERANK_ENABLED", True)
    monkeypatch.setattr(reranker, "RERANK_BACKEND", "local")

    def boom(q, docs):
        raise RuntimeError("model down")

    monkeypatch.setattr(reranker, "_rerank_local", boom)
    cands = [item(1), item(2), item(3)]
    assert reranker.rerank("q", cands, top_n=2) == cands[:2]


# ---------------- hybrid（召回层用 mock） ----------------
@pytest.fixture
def no_enrich(monkeypatch):
    def fake(items, category):
        for it in items:
            it["_text"] = it.get("title", "")
        return items
    monkeypatch.setattr(hs, "_enrich", fake)


def test_hybrid_merges_both_channels(monkeypatch, no_enrich):
    monkeypatch.setattr(hs, "keyword_search", lambda *a, **k: [item(1), item(2)])
    monkeypatch.setattr(hs, "vector_search", lambda *a, **k: [item(2), item(3)])
    monkeypatch.setattr(hs.reranker, "RERANK_ENABLED", False)
    out = hs.hybrid_search("q", limit=5)
    assert {r["news_id"] for r in out} == {1, 2, 3}
    assert out[0]["news_id"] == 2                      # 两路都命中
    assert out[0]["channels"] == ["keyword", "vector"]
    assert not any("_text" in r for r in out)          # 内部字段不外泄


def test_hybrid_survives_vector_failure(monkeypatch, no_enrich):
    def boom(*a, **k):
        raise RuntimeError("chroma down")
    monkeypatch.setattr(hs, "keyword_search", lambda *a, **k: [item(1)])
    monkeypatch.setattr(hs, "vector_search", boom)
    monkeypatch.setattr(hs.reranker, "RERANK_ENABLED", False)
    assert [r["news_id"] for r in hs.hybrid_search("q")] == [1]


def test_hybrid_limit_clamped_and_snippet(monkeypatch, no_enrich):
    long = "x" * 1000
    many = [item(i, summary=long) for i in range(1, 30)]
    monkeypatch.setattr(hs, "keyword_search", lambda *a, **k: many)
    monkeypatch.setattr(hs, "vector_search", lambda *a, **k: [])
    monkeypatch.setattr(hs.reranker, "RERANK_ENABLED", False)
    out = hs.hybrid_search("q", limit=999)
    assert len(out) == hs.MAX_LIMIT
    assert len(out[0]["summary"]) <= hs.SNIPPET_CHARS + 1


def test_hybrid_uses_rerank_score(monkeypatch, no_enrich):
    monkeypatch.setattr(hs, "keyword_search", lambda *a, **k: [item(1), item(2)])
    monkeypatch.setattr(hs, "vector_search", lambda *a, **k: [])
    monkeypatch.setattr(hs.reranker, "RERANK_ENABLED", True)
    monkeypatch.setattr(hs.reranker, "rerank",
                        lambda q, c, top_n=None: [dict(c[1], rerank_score=0.99)])
    out = hs.hybrid_search("q", limit=1)
    assert out[0]["news_id"] == 2 and out[0]["score"] == 0.99


# ---------------- 真 SQLite（临时库） ----------------
@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    from storage import connection
    monkeypatch.setattr(connection, "DB_PATH", tmp_path / "news.db")
    monkeypatch.setattr(connection, "_initialized", False)
    conn = connection.get_connection()
    rows = [
        (1, "强化学习新突破", "PPO 算法改进", "AI研究", 9, "analyzed", 300),
        (2, "OpenAI 发布新模型", "强化学习用于推理", "产品发布", 8, "embedded", 200),
        (3, "芯片行业动态", "与本主题无关", "硬件", 5, "analyzed", 100),
        (4, "强化学习旧闻（未分析）", "status=raw 不应被检索", "AI研究", 9, "raw", 50),
    ]
    for nid, title, summ, cat, imp, st, ts in rows:
        conn.execute(
            "INSERT INTO news(id,url,title,summary,llm_category,importance,status,published_ts)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (nid, f"http://x/{nid}", title, summ, cat, imp, st, ts),
        )
    conn.commit()
    conn.close()
    return tmp_path


def test_keyword_search_real_sql(temp_db):
    out = keyword_search("强化学习", limit=10)
    ids = [r["news_id"] for r in out]
    assert ids[0] == 1                   # 标题命中 > 仅摘要命中
    assert set(ids) == {1, 2}            # raw 状态被过滤
    assert out[0]["category"] == "AI研究"


def test_keyword_search_category_and_browse(temp_db):
    assert [r["news_id"] for r in keyword_search("强化学习", category="产品发布")] == [2]
    browse = keyword_search(None, category="AI研究")   # 无关键词：按分类浏览
    assert [r["news_id"] for r in browse] == [1]


def test_enrich_drops_stale_vector_ids_and_fills(temp_db):
    items = [
        {"news_id": 1, "title": None, "summary": "向量里的旧文本"},
        {"news_id": 999, "title": "库里已删除"},     # 脏数据
    ]
    out = hs._enrich(items, category=None)
    assert [i["news_id"] for i in out] == [1]
    assert out[0]["title"] == "强化学习新突破"          # 以 SQLite 为准补全
    assert out[0]["summary"] == "PPO 算法改进"


def test_enrich_category_filter(temp_db):
    items = [{"news_id": 1}, {"news_id": 2}]
    out = hs._enrich(items, category="产品发布")
    assert [i["news_id"] for i in out] == [2]


def test_db_facade_exports():
    import storage.db as db
    for name in ["get_connection", "query_news", "fetch_news_by_ids", "report_exists",
                 "fetch_report_by_date", "fetch_trends", "fetch_tech_news",
                 "normalize_keyword", "update_fields", "fetch_by_status",
                 "fetch_important_recent", "fetch_reports_range",
                 "fetch_latest_report", "fetch_all_report_indexes",
                 "table_columns", "table_exists", "init_db"]:
        assert hasattr(db, name), name


def test_hybrid_dedups_when_vector_metadata_has_no_news_id(temp_db, monkeypatch):
    """向量元数据缺 news_id：应按 url 补齐，使同一篇文章只出现一次并标记两路命中"""
    monkeypatch.setattr(hs, "keyword_search", lambda *a, **k: [
        {"news_id": 1, "title": "强化学习新突破", "url": "http://x/1"}])
    monkeypatch.setattr(hs, "vector_search", lambda *a, **k: [
        {"news_id": None, "title": None, "url": "http://x/1", "summary": "向量文本"}])
    monkeypatch.setattr(hs.reranker, "RERANK_ENABLED", False)
    out = hs.hybrid_search("强化学习", limit=5)
    assert len(out) == 1
    assert out[0]["news_id"] == 1
    assert out[0]["channels"] == ["keyword", "vector"]