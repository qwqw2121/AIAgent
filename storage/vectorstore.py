# storage/vectorstore.py
import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_chroma import Chroma

# 🌟 核心修改：引入 DashScope 原生 Embeddings
from langchain_community.embeddings import DashScopeEmbeddings

# 1. 加载 .env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# 2. 配置读取
EMBED_MODEL = str(os.getenv("LLM_EMBEDING", "text-embedding-v3")).strip()
API_KEY = str(os.getenv("LLM_API_KEY", "")).strip()

if not API_KEY:
    raise ValueError("❌ 请在 .env 中配置 LLM_API_KEY")

print(f"✅ 成功读取 Embedding 配置: Model={EMBED_MODEL} (使用 DashScope 原生接口)")

# 🌟 3. 初始化 DashScope 原生 Embeddings (彻底告别 OpenAI 兼容模式的 Bug)
embeddings = DashScopeEmbeddings(
    model=EMBED_MODEL,
    dashscope_api_key=API_KEY,  # 注意：这里的参数名是 dashscope_api_key
)

# 4. 初始化 Chroma
PERSIST_DIR = os.getenv("VECTOR_DB_PATH", "storage/vector_db")
vectorstore = Chroma(
    collection_name="news_embeddings",
    embedding_function=embeddings,
    persist_directory=PERSIST_DIR,
)

# ============================================================
# 5. 业务接口 (保持不变)
# ============================================================
def upsert_news(news_id: int, title: str, summary: str, metadata: dict):
    """将新闻写入向量库 (带严格空值拦截)"""
    safe_title = str(title).strip() if title is not None else "未知标题"
    safe_summary = str(summary).strip() if summary is not None else ""
    text_to_embed = f"{safe_title}\n{safe_summary}".strip()
    
    if not text_to_embed or text_to_embed.lower() in ["none", "none\nnone"]:
        print(f"⚠️ 拦截: ID={news_id} 的文本内容为空，跳过向量入库")
        return
    
    try:
        vectorstore.add_texts(
            texts=[text_to_embed],
            metadatas=[{**metadata, "news_id": news_id}],
            ids=[str(news_id)],
        )
    except Exception as e:
        print(f"❌ ID={news_id} 向量入库失败: {e}")
        raise

def get_retriever(k=5):
    return vectorstore.as_retriever(search_kwargs={"k": k})