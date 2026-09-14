# storage/vectorstore.py
import os
from typing import List
from langchain_chroma import Chroma
from FlagEmbedding import BGEM3FlagModel

MODEL_PATH = os.getenv("BGE_MODEL_PATH", "/mnt/d/AI_Models/bge-m3")
PERSIST_DIR = "storage/vector_db"

# BGE-M3 官方推荐的检索指令（query 侧）
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class BGE3Embeddings:
    """把 BGEM3FlagModel 适配成 LangChain Embeddings 接口。"""

    def __init__(self, model_path: str, device: str = "cpu", use_fp16: bool = False):
        self.model = BGEM3FlagModel(model_path, use_fp16=use_fp16, device=device)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        out = self.model.encode(texts, batch_size=8, max_length=8192)
        return out["dense_vecs"].tolist()

    # def embed_query(self, text: str) -> List[float]:
    #     out = self.model.encode([QUERY_INSTRUCTION + text], max_length=8192)
    #     return out["dense_vecs"][0].tolist()
    # def embed_query(self, text: str) -> List[float]:
    #     out = self.model.encode(
    #         [QUERY_INSTRUCTION + text],
    #         batch_size=1,
    #         max_length=8192,
    #     )
    #     return out["dense_vecs"][0].tolist()
    def embed_query(self, text: str) -> List[float]:
        # 🌟 核心修复：防御性检查，确保 text 绝对是纯字符串
        if isinstance(text, list):
            # 如果是 LangChain 的消息列表 (如 [HumanMessage(...)])，提取最后一条的文本内容
            if len(text) > 0 and hasattr(text[-1], 'content'):
                text = str(text[-1].content)
            else:
                text = str(text)
        elif not isinstance(text, str):
            text = str(text)
            
        # 现在 text 已经是安全的纯字符串，可以安全拼接和 encode
        out = self.model.encode(
            [QUERY_INSTRUCTION + text],
            batch_size=1,
            max_length=8192,
        )
        return out["dense_vecs"][0].tolist()

embeddings = BGE3Embeddings(MODEL_PATH, device="cpu", use_fp16=False)

vectorstore = Chroma(
    collection_name="news_embeddings",
    embedding_function=embeddings,
    persist_directory=PERSIST_DIR,
)


def upsert_news(news_id: int, title: str, summary: str, metadata: dict):
    vectorstore.add_texts(
        texts=[f"{title}\n{summary}"],
        metadatas=[{**metadata, "news_id": news_id}],
        ids=[str(news_id)],
    )


def get_retriever(k=5):
    return vectorstore.as_retriever(search_kwargs={"k": k})