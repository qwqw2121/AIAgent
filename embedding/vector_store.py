# embedding/vector_store.py
"""
向量库唯一入口。所有读写都通过 get_vector_store() 拿到的单例，
保证全项目使用同一个 Chroma client、同一个集合、同一个路径。
"""
import os
from pathlib import Path

import chromadb
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COLLECTION_NAME = "ai_news"


def resolve_persist_path() -> Path:
    """VECTOR_DB_PATH 为相对路径时，相对项目根目录解析，不依赖运行时 cwd。"""
    raw = os.getenv("VECTOR_DB_PATH") or (PROJECT_ROOT / "storage" / "vector_db")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


class VectorStore:
    """Chroma 向量数据库封装"""

    def __init__(
        self,
        persist_directory: str | Path | None = None,
        collection_name: str = COLLECTION_NAME,
    ):
        persist_path = (
            Path(persist_directory).expanduser()
            if persist_directory
            else resolve_persist_path()
        )
        persist_path.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=str(persist_path))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ---------- 属性 ----------
    @property
    def space(self) -> str:
        metadata = getattr(self.collection, "metadata", None) or {}
        return str(metadata.get("hnsw:space", "cosine")).lower()

    # ---------- 写 ----------
    def add_news(
        self,
        news_id: int,
        embedding: list[float],
        embedding_text: str,
        metadata: dict,
    ):
        self.collection.upsert(
            ids=[str(news_id)],
            embeddings=[embedding],
            documents=[embedding_text],
            metadatas=[metadata],
        )

    def delete(self, news_id: int):
        self.collection.delete(ids=[str(news_id)])

    # ---------- 读 ----------
    def exists(self, news_id: int) -> bool:
        result = self.collection.get(ids=[str(news_id)])
        return len(result["ids"]) > 0

    def get_embedding(self, news_id: int):
        """取单条向量，不存在返回 None"""
        return self.get_embeddings([news_id]).get(int(news_id))

    def get_embeddings(self, news_ids, batch_size: int = 500) -> dict:
        """批量取向量，返回 {news_id: embedding}，缺失的不在结果里"""
        ids = [str(i) for i in news_ids]
        out: dict = {}
        for start in range(0, len(ids), batch_size):
            res = self.collection.get(
                ids=ids[start:start + batch_size],
                include=["embeddings"],
            )
            embs = res.get("embeddings")
            if embs is None:
                continue
            for _id, emb in zip(res.get("ids") or [], embs):
                if emb is not None:
                    out[int(_id)] = emb
        return out

    def search_similar(self, embedding: list[float], top_k: int = 5):
        return self.collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
        )

    def get_all(self):
        return self.collection.get(include=["embeddings", "documents", "metadatas"])


_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """全局单例"""
    global _store
    if _store is None:
        _store = VectorStore()
    return _store