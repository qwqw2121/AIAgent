# embedding/embed_news.py

import os
import sqlite3
import json
import time
from pathlib import Path

# =====================================================
# 1. 全局配置
# =====================================================
DB_PATH = os.getenv("NEWS_DB_PATH", Path(__file__).parent.parent / "storage/news.db")

# 🌟 核心开关：'online' (在线API) 或 'local' (本地BGE-M3)
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "online").lower() 

# 在线模型配置
EMBED_MODEL = os.getenv("LLM_EMBEDING", "text-embedding-v3")

# 本地模型配置
BGE_MODEL_PATH = os.getenv("BGE_MODEL_PATH", "/mnt/d/AI_Models/bge-m3")

print(f"🚀 Embedding 模式: {EMBEDDING_PROVIDER.upper()}")

# =====================================================
# 2. 引擎 1：本地 BGE-M3 (懒加载)
# =====================================================
_local_model = None

def get_local_model():
    global _local_model
    if _local_model is None and EMBEDDING_PROVIDER == 'local':
        os.environ['CUDA_VISIBLE_DEVICES'] = ''  # 强制 CPU
        print(f"🔄 正在加载本地 BGE-M3 模型: {BGE_MODEL_PATH} (CPU)")
        from FlagEmbedding import BGEM3FlagModel
        _local_model = BGEM3FlagModel(BGE_MODEL_PATH, use_fp16=False, device="cpu")
    return _local_model

# =====================================================
# 3. 引擎 2：在线 API (懒加载)
# =====================================================
_online_client = None

def get_online_client():
    global _online_client
    if _online_client is None and EMBEDDING_PROVIDER == 'online':
        from openai import OpenAI
        API_KEY = os.getenv("LLM_API_KEY")
        BASE_URL = os.getenv("LLM_BASE_URL")
        if not API_KEY or not BASE_URL:
            raise ValueError("❌ 使用在线 Embedding 需要在 .env 中配置 LLM_API_KEY 和 LLM_BASE_URL")
        _online_client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _online_client

# =====================================================
# 4. 统一 Embedding 接口 (自动路由)
# =====================================================
def get_embedding(text: str):
    """
    根据 EMBEDDING_PROVIDER 自动选择本地或在线模型生成向量
    返回: List[float] 或 None
    """
    if not text or len(text.strip()) < 5:
        return None
    
    try:
        if EMBEDDING_PROVIDER == 'online':
            # 🌟 在线 API 调用
            client = get_online_client()
            response = client.embeddings.create(
                model=EMBED_MODEL,
                input=text
            )
            return response.data[0].embedding
            
        else:
            # 🌟 本地 BGE-M3 调用
            model = get_local_model()
            if model is None:
                raise RuntimeError("本地模型未初始化，请检查 EMBEDDING_PROVIDER 配置")
            
            result = model.encode(text)
            embedding = result['dense_vecs']
            
            # 兼容 numpy array 和 list
            if hasattr(embedding, 'tolist'):
                embedding = embedding.tolist()
            return list(embedding)
            
    except Exception as e:
        print(f"❌ Embedding 生成失败 ({EMBEDDING_PROVIDER}): {e}")
        return None

# =====================================================
# 5. 辅助函数 (保持不变)
# =====================================================
from embedding.vector_store import VectorStore
vector_store = VectorStore()

# embedding/embed_news.py (只需修改 build_embedding_text 函数)

def build_embedding_text(row):
    """使用LLM分析结果构造Embedding文本 (严格防御版)"""
    # 🌟 强制转字符串，杜绝 None
    title = str(row["title"]).strip() if row["title"] else "未知标题"
    summary = str(row["summary"]).strip() if row["summary"] else "无摘要"
    category = str(row["llm_category"]).strip() if row["llm_category"] else "未分类"

    keywords = row["keywords"] or []
    if isinstance(keywords, str):
        try:
            keywords = json.loads(keywords)
        except json.JSONDecodeError:
            keywords = [keywords]

    keywords_text = ", ".join(str(k) for k in keywords) if isinstance(keywords, list) else str(keywords)

    text = f"""标题：{title}
摘要：{summary}
分类：{category}
关键词：{keywords_text}""".strip()
    
    # 🚨 确保绝不返回空字符串
    return text if text else "无有效内容"
def load_news():
    """从 SQLite 读取待向量化的新闻"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 注意：这里假设你的状态是 'analyzed'，如果是 'embed_failed' 请自行修改
    cursor.execute("""
        SELECT id, title, summary, llm_category, keywords, 
               source, category, published
        FROM news 
        WHERE status = 'analyzed' OR status = 'embed_failed'
        ORDER BY id
    """)

    rows = cursor.fetchall()
    conn.close()
    return rows

def update_status(news_id, status):
    """更新新闻状态"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE news SET status = ? WHERE id = ?", (status, news_id))
    conn.commit()
    conn.close()

# =====================================================
# 6. 测试与主流程
# =====================================================
def test_embedding():
    """测试 Embedding 是否正常工作"""
    test_text = "测试文本：这是一条关于AI的新闻"
    print(f"\n🧪 测试 Embedding ({EMBEDDING_PROVIDER})...")
    
    start_time = time.time()
    embedding = get_embedding(test_text)
    cost_time = time.time() - start_time
    
    if embedding:
        print(f"   ✅ 成功生成向量 (耗时: {cost_time:.2f}s)")
        print(f"   向量维度: {len(embedding)}")
        return True
    else:
        print(f"   ❌ 测试失败")
        return False

def run():
    """主流程：生成所有新闻的向量"""
    if not test_embedding():
        print("❌ Embedding 测试失败，请检查配置")
        return
    
    news_list = load_news()
    print(f"\n📊 待向量化新闻：{len(news_list)} 条")
    
    success_count = 0
    fail_count = 0
    
    for i, row in enumerate(news_list, 1):
        news_id = row["id"]
        print(f"\n[{i}/{len(news_list)}] 处理 ID={news_id}")
        
        try:
            # 1. 构造文本
            embedding_text = build_embedding_text(row)
            if not embedding_text.strip():
                print(f"  ⚠️ 跳过: 没有可 Embedding 的内容")
                continue
            
            # 2. 生成向量
            embedding = get_embedding(embedding_text)
            if embedding is None:
                fail_count += 1
                continue
            
            # 3. 存入向量数据库
            vector_store.add_news(
                news_id=news_id,
                embedding=embedding,
                embedding_text=embedding_text,
                metadata={
                    "news_id": news_id,
                    "title": row["title"] or "",
                    "source": row["source"] or "",
                    "category": row["category"] or "",
                    "published_at": row["published"] or "",
                }
            )
            
            # 4. 更新状态
            update_status(news_id, "embedded")
            success_count += 1
            print(f"  ✅ 完成")
            
        except Exception as e:
            fail_count += 1
            print(f"  ❌ 失败: {e}")
            import traceback
            traceback.print_exc()
            
        # 🌟 优化：在线 API 不需要 sleep，本地模型 CPU 跑本身就有延迟
        # 如果担心在线 API 限流，可以取消注释下面这行
        # time.sleep(0.1) 
    
    print(f"\n{'='*60}")
    print(f"📊 Embedding 任务完成")
    print(f"  ✅ 成功: {success_count} 条")
    print(f"  ❌ 失败: {fail_count} 条")
    return {"total": len(news_list), "success": success_count, "failed": fail_count}

if __name__ == "__main__":
    run()