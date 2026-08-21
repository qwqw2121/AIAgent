''' ② Embedding → Chroma   
向量 → 向量数据库
Embedding
    ↓
Vector DB
'''

# embedding/vector_store.py

from pathlib import Path
import chromadb


# =========================
# 配置
# =========================
# BASE_DIR = Path(__file__).parent.parent
# # DB_PATH = BASE_DIR / "storage/news.db"
# VECTOR_DB_PATH = BASE_DIR / "storage/vector_db"
# DB_PATH = Path("storage/news.db") #绝对路径
import os
VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", Path(__file__).parent.parent / "storage/vector_db")
class VectorStore:
    """
    Chroma 向量数据库封装
    """

    def __init__(
        self,
        persist_directory: str = str(VECTOR_DB_PATH),
        collection_name: str = "ai_news",
    ):
        self.client = chromadb.PersistentClient(
            path=persist_directory
        )

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={
                "hnsw:space": "cosine"
            }
        )

    # =========================
    # 添加新闻
    # =========================

    def add_news(
        self,
        news_id: int,
        embedding: list[float],
        embedding_text: str,
        metadata: dict,
    ):
        """
        将一条新闻加入向量数据库
        """

        self.collection.upsert(
            ids=[str(news_id)],
            embeddings=[embedding],
            documents=[embedding_text],
            metadatas=[metadata],
        )

    # =========================
    # 查询相似新闻
    # =========================

    def search_similar(
        self,
        embedding: list[float],
        top_k: int = 5,
    ):
        """
        根据向量查询最相似的新闻
        """

        result = self.collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
        )

        return result

    # =========================
    # 获取所有向量
    # =========================

    def get_all(self):
        """
        获取当前向量数据库中的所有新闻
        """

        return self.collection.get(
            include=[
                "embeddings",
                "documents",
                "metadatas",
            ]
        )

    # =========================
    # 根据新闻ID判断是否存在
    # =========================

    def exists(self, news_id: int) -> bool:

        result = self.collection.get(
            ids=[str(news_id)]
        )

        return len(result["ids"]) > 0

    # =========================
    # 删除
    # =========================

    def delete(self, news_id: int):

        self.collection.delete(
            ids=[str(news_id)]
        )