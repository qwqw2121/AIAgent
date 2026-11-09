import os
from pathlib import Path

import chromadb
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COLLECTION_NAME = "ai_news"


def resolve_persist_path() -> Path:
    raw = os.getenv("VECTOR_DB_PATH") or (
        PROJECT_ROOT / "storage" / "vector_db"
    )

    path = Path(raw).expanduser()

    if not path.is_absolute():
        path = PROJECT_ROOT / path

    return path


class VectorStore:

    def __init__(
        self,
        persist_directory=None,
        collection_name=COLLECTION_NAME,
    ):
        persist_path = (
            Path(persist_directory).expanduser()
            if persist_directory
            else resolve_persist_path()
        )

        persist_path.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(persist_path)
        )

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def space(self):
        metadata = getattr(self.collection, "metadata", None) or {}
        return str(metadata.get("hnsw:space", "cosine")).lower()

    def add_news(
        self,
        news_id: int,
        embedding: list[float],
        embedding_text: str,
        metadata: dict,
    ):
        """新增或更新新闻向量"""

        meta = dict(metadata)

        meta["news_id"] = int(news_id)

        if meta.get("published_ts") is not None:
            meta["published_ts"] = int(meta["published_ts"])

        self.collection.upsert(
            ids=[str(news_id)],
            embeddings=[embedding],
            documents=[embedding_text],
            metadatas=[meta],
        )

    def delete(self, news_id: int):
        self.collection.delete(ids=[str(news_id)])

    def exists(self, news_id: int) -> bool:
        result = self.collection.get(ids=[str(news_id)])
        return len(result["ids"]) > 0

    def get_embedding(self, news_id: int):
        return self.get_embeddings([news_id]).get(int(news_id))

    def get_embeddings(self, news_ids, batch_size=500):
        ids = [str(i) for i in news_ids]
        out = {}

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

    def search_similar(self, embedding, top_k=5, where=None):
        kwargs = {
            "query_embeddings": [embedding],
            "n_results": top_k,
        }

        if where:
            kwargs["where"] = where

        return self.collection.query(**kwargs)

    def get_all(self):
        return self.collection.get(
            include=["embeddings", "documents", "metadatas"]
        )


_store = None


def get_vector_store():
    global _store

    if _store is None:
        _store = VectorStore()

    return _store