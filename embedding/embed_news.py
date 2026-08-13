'''① 新闻 → Embedding
从SQLite读取：
extract_status = success
analysis_status = success
embedding_status = pending
        ↓
构造 embedding_text
        ↓
Embedding Model
        ↓
得到 vector
        ↓
'''

# embedding/embed_news.py

# diagnose.py
# embedding/embed_news.py (完整修复版)

import os
import sqlite3
import json
import numpy as np
from pathlib import Path
import time

from FlagEmbedding import BGEM3FlagModel
from vector_store import VectorStore

# =====================================================
# 强制使用 CPU（解决 CUDA 不兼容问题）
# =====================================================

os.environ['CUDA_VISIBLE_DEVICES'] = ''  # 禁用 GPU

# =====================================================
# 配置
# =====================================================

MODEL_PATH = "/mnt/d/AI_Models/bge-m3"
DB_PATH = Path(__file__).parent.parent / "storage/news.db"

print(f"🔄 正在从本地加载 BGE-M3 模型...")
print(f"   路径: {MODEL_PATH}")
print(f"   设备: CPU (强制)")

# =====================================================
# 加载模型（使用 CPU）
# =====================================================

try:
    model = BGEM3FlagModel(
        MODEL_PATH,
        use_fp16=False,      # CPU 不支持 fp16
        device="cpu"         # 强制使用 CPU
    )
    print("✅ BGE-M3 模型加载完成 (CPU 模式)")
except Exception as e:
    print(f"❌ 模型加载失败: {e}")
    print("请检查模型路径是否正确，或尝试重新下载模型")
    exit(1)

# =====================================================
# 初始化向量存储
# =====================================================

vector_store = VectorStore()


# =====================================================
# 构造 Embedding 文本
# =====================================================

def build_embedding_text(row):
    """使用LLM分析结果构造Embedding文本"""
    title = row["title"] or ""
    summary = row["summary"] or ""
    category = row["llm_category"] or ""

    keywords = row["keywords"] or []
    if isinstance(keywords, str):
        try:
            keywords = json.loads(keywords)
        except json.JSONDecodeError:
            keywords = [keywords]

    keywords_text = ", ".join(str(k) for k in keywords) if isinstance(keywords, list) else str(keywords)

    return f"""标题：{title}
摘要：{summary}
分类：{category}
关键词：{keywords_text}""".strip()


# =====================================================
# 调用 BGE-M3 Embedding（修复版）
# =====================================================

def get_embedding(text: str):
    """
    使用 BGE-M3 生成向量
    
    注意：BGE-M3 返回字典，需要取 'dense_vecs' 键的值
    """
    if not text or len(text.strip()) < 5:
        return None
    
    try:
        # ✅ BGE-M3 返回字典
        result = model.encode(text)
        
        # ✅ 调试：查看返回类型
        print(f"🔍 result 类型: {type(result)}")
        print(f"🔍 result 键: {result.keys() if hasattr(result, 'keys') else '不是字典'}")
        
        # ✅ 取稠密向量
        embedding = result['dense_vecs']
        
        # ✅ 如果是 numpy array，转为 list
        if hasattr(embedding, 'tolist'):
            embedding = embedding.tolist()
        
        # ✅ 确保是 list
        if not isinstance(embedding, list):
            embedding = list(embedding)
        
        return embedding
        
    except Exception as e:
        print(f"❌ Embedding 生成失败: {e}")
        return None


# =====================================================
# 查询待向量化新闻
# =====================================================

def load_news():
    """从 SQLite 读取待向量化的新闻"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, summary, llm_category, keywords, 
               source, category, published
        FROM news 
        WHERE status = 'analyzed'
        ORDER BY id
    """)

    rows = cursor.fetchall()
    conn.close()
    return rows


# =====================================================
# 更新状态
# =====================================================

def update_status(news_id, status):
    """更新新闻状态"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE news
        SET status = ?
        WHERE id = ?
    """, (status, news_id))

    conn.commit()
    conn.close()


# =====================================================
# 测试函数
# =====================================================

def test_embedding():
    """测试 Embedding 是否正常工作"""
    test_text = "测试文本：这是一条关于AI的新闻"
    print(f"\n🧪 测试 Embedding...")
    print(f"   输入: {test_text}")
    
    embedding = get_embedding(test_text)
    
    if embedding:
        print(f"   ✅ 成功生成向量")
        print(f"   向量类型: {type(embedding)}")
        print(f"   向量长度: {len(embedding)}")
        print(f"   前5个值: {embedding[:5]}")
        return True
    else:
        print(f"   ❌ 测试失败")
        return False


# =====================================================
# 主流程
# =====================================================

def main():
    """主流程：生成所有新闻的向量"""
    
    # 测试 Embedding
    if not test_embedding():
        print("❌ Embedding 测试失败，请检查模型加载")
        return
    
    # 加载新闻
    news_list = load_news()
    print(f"\n📊 待向量化新闻：{len(news_list)} 条")
    
    success_count = 0
    fail_count = 0
    skip_count = 0
    
    for i, row in enumerate(news_list, 1):
        news_id = row["id"]
        
        print(f"\n[{i}/{len(news_list)}] 处理 ID={news_id}")
        
        try:
            # 1. 构造文本
            embedding_text = build_embedding_text(row)
            
            if not embedding_text.strip():
                print(f"  ⚠️ 跳过: 没有可 Embedding 的内容")
                skip_count += 1
                continue
            
            print(f"  📝 文本长度: {len(embedding_text)} 字符")
            
            # 2. 生成向量
            embedding = get_embedding(embedding_text)
            
            if embedding is None:
                print(f"  ❌ 生成向量失败")
                fail_count += 1
                continue
            
            print(f"  ✅ 向量生成成功，维度: {len(embedding)}")
            
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
                    "published_at": row["published"]  or "",
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
        
        # 避免请求过快
        time.sleep(0.5)
    
    # 统计结果
    print(f"\n{'='*60}")
    print(f"📊 Embedding 任务完成")
    print(f"  ✅ 成功: {success_count} 条")
    print(f"  ❌ 失败: {fail_count} 条")
    print(f"  ⏭️ 跳过: {skip_count} 条")
    print(f"  📝 总计: {len(news_list)} 条")


if __name__ == "__main__":
    main()