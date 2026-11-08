# retrieval/reranker.py
"""
可选精排。通过环境变量控制，默认关闭，任何失败都回退为原顺序。

  RERANK_ENABLED=1
  RERANK_BACKEND=dashscope | local     （默认 dashscope，复用 LLM_API_KEY）
  RERANK_MODEL=...                     （默认 gte-rerank / BAAI/bge-reranker-base）

dashscope 后端：pip install dashscope
local 后端   ：pip install sentence-transformers
"""

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
import os
import sys
import threading

RERANK_ENABLED = os.getenv("RERANK_ENABLED", "0").strip().lower() in ("1", "true", "yes")
RERANK_BACKEND = os.getenv("RERANK_BACKEND", "dashscope").strip().lower()
_DEFAULT_MODELS = {"dashscope": "gte-rerank", "local": "BAAI/bge-reranker-base"}
RERANK_MODEL = os.getenv("RERANK_MODEL", "").strip() or _DEFAULT_MODELS.get(RERANK_BACKEND, "")
API_KEY = os.getenv("LLM_API_KEY", "").strip()

MAX_DOC_CHARS = 500

_local_model = None
_local_lock = threading.Lock()


def is_enabled() -> bool:
    return RERANK_ENABLED


def _doc_text(item: dict) -> str:
    text = item.get("_text") or f"{item.get('title') or ''}\n{item.get('summary') or ''}"
    return text.strip()[:MAX_DOC_CHARS]


def _get_local_model():
    global _local_model
    if _local_model is None:
        with _local_lock:
            if _local_model is None:
                from sentence_transformers import CrossEncoder
                _local_model = CrossEncoder(RERANK_MODEL)
    return _local_model


def _rerank_local(query: str, docs: list[str]) -> list[tuple[int, float]]:
    model = _get_local_model()
    scores = model.predict([(query, d) for d in docs])
    return [(i, float(s)) for i, s in enumerate(scores)]


def _rerank_dashscope(query: str, docs: list[str], top_n: int) -> list[tuple[int, float]]:
    import dashscope
    resp = dashscope.TextReRank.call(
        model=RERANK_MODEL,
        query=query,
        documents=docs,
        top_n=top_n,
        return_documents=False,
        api_key=API_KEY,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"dashscope rerank {resp.status_code}: {getattr(resp, 'message', '')}")
    return [(r["index"], float(r["relevance_score"])) for r in resp.output["results"]]


def rerank(query: str, candidates: list[dict], top_n: int | None = None) -> list[dict]:
    """
    对候选精排，返回按 rerank_score 降序的前 top_n 条（附加 rerank_score 字段）。
    未启用 / 候选过少 / 调用失败时，原样返回（截断到 top_n）。
    """
    top_n = top_n or len(candidates)
    if not RERANK_ENABLED or len(candidates) < 2 or not (query or "").strip():
        return candidates[:top_n]

    docs = [_doc_text(c) for c in candidates]
    try:
        if RERANK_BACKEND == "local":
            pairs = _rerank_local(query, docs)
        elif RERANK_BACKEND == "dashscope":
            pairs = _rerank_dashscope(query, docs, top_n=len(docs))
        else:
            raise ValueError(f"未知 RERANK_BACKEND: {RERANK_BACKEND}")
    except Exception as e:
        print(f"⚠️ rerank 失败，回退融合排序: {type(e).__name__}: {e}", file=sys.stderr)
        return candidates[:top_n]

    pairs.sort(key=lambda p: p[1], reverse=True)
    out = []
    for idx, score in pairs[:top_n]:
        item = dict(candidates[idx])
        item["rerank_score"] = round(score, 4)
        out.append(item)
    return out


def warmup() -> None:
    """预加载本地模型，避免首次请求卡顿（dashscope 后端无需预热）"""
    if RERANK_ENABLED and RERANK_BACKEND == "local":
        try:
            _get_local_model()
            print(f"✅ Reranker 预热完成: {RERANK_MODEL}", file=sys.stderr)
        except Exception as e:
            print(f"⚠️ Reranker 预热失败: {e}", file=sys.stderr)