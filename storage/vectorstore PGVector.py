# 未来的 storage/vectorstore.py (PGVector 版本)
import os
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import PGVector

load_dotenv()

# 1. Embedding 配置 (保持不变，依然用在线 API)
EMBED_MODEL = os.getenv("LLM_EMBEDING", "text-embedding-v3")
API_KEY = os.getenv("LLM_API_KEY")
BASE_URL = os.getenv("LLM_BASE_URL")

embeddings = OpenAIEmbeddings(
    model=EMBED_MODEL,
    openai_api_key=API_KEY,
    openai_api_base=BASE_URL,
)

# 2. PostgreSQL 连接字符串 (例如: postgresql+psycopg2://user:pass@localhost:5432/news_db)
CONNECTION_STRING = os.getenv("DATABASE_URL") 
COLLECTION_NAME = "news_embeddings"

# 3. 初始化 PGVector (它会自动在 PG 中创建表和 pgvector 扩展)
vectorstore = PGVector(
    collection_name=COLLECTION_NAME,
    connection_string=CONNECTION_STRING,
    embedding_function=embeddings,
    use_jsonb=True,  # 🌟 关键：使用 JSONB 存储 metadata，支持高效的混合查询
)

# 4. 你的业务接口几乎不用改！
def upsert_news(news_id: int, title: str, summary: str, metadata: dict):
    safe_title = str(title).strip() if title else "未知标题"
    safe_summary = str(summary).strip() if summary else ""
    text_to_embed = f"{safe_title}\n{safe_summary}".strip()
    
    if not text_to_embed or text_to_embed.lower() in ["none", "none\nnone"]:
        return
    
    # PGVector 的 add_texts 用法与 Chroma 完全一致
    vectorstore.add_texts(
        texts=[text_to_embed],
        metadatas=[{**metadata, "news_id": news_id}],
        ids=[str(news_id)],
    )

def get_retriever(k=5):
    return vectorstore.as_retriever(search_kwargs={"k": k})