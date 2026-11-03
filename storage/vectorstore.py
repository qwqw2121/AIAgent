# storage/vectorstore.py
"""
LangChain 适配层，只用于 MCP / 检索。
复用 embedding.vector_store 的同一个 client 和集合，不再单独建库。
写入请统一走 embedding_task -> VectorStore.add_news。
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings

from embedding.vector_store import get_vector_store

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

EMBED_MODEL = str(os.getenv("LLM_EMBEDING", "text-embedding-v3")).strip()
API_KEY = str(os.getenv("LLM_API_KEY", "")).strip()

if not API_KEY:
    raise ValueError("❌ 请在 .env 中配置 LLM_API_KEY")

# 打印到 stderr，避免污染 MCP stdio 协议
print(f"✅ Embedding 配置: Model={EMBED_MODEL} (DashScope)", file=sys.stderr)

embeddings = DashScopeEmbeddings(
    model=EMBED_MODEL,
    dashscope_api_key=API_KEY,
    max_retries=1,
)

_store = get_vector_store()


def build_vectorstore() -> Chroma:
    return Chroma(
        client=_store.client,
        collection_name=_store.collection.name,
        embedding_function=embeddings,
        collection_metadata={"hnsw:space": "cosine"},
    )


vectorstore = build_vectorstore()


def upsert_news(news_id: int, title: str, summary: str, metadata: dict):
    """写入向量库（保留兼容；正常流程应由 embedding_task 写入）"""
    safe_title = str(title).strip() if title is not None else "未知标题"
    safe_summary = str(summary).strip() if summary is not None else ""
    text = f"{safe_title}\n{safe_summary}".strip()

    if not text or text.lower() in ["none", "none\nnone"]:
        print(f"⚠️ 拦截: ID={news_id} 的文本内容为空，跳过向量入库", file=sys.stderr)
        return

    try:
        emb = embeddings.embed_query(text)
        _store.add_news(news_id, emb, text, {**metadata, "news_id": news_id})
    except Exception as e:
        print(f"❌ ID={news_id} 向量入库失败: {e}", file=sys.stderr)
        raise


def get_retriever(k=5):
    return vectorstore.as_retriever(search_kwargs={"k": k})