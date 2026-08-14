''' 
一篇新闻 → 找相似新闻
'''

# embedding/similarity.py

import os
from pathlib import Path

from FlagEmbedding import BGEM3FlagModel

from vector_store import VectorStore

os.environ['CUDA_VISIBLE_DEVICES'] = ''

DB_PATH = Path(__file__).resolve().parent.parent / "storage/news.db"
MODEL_PATH = "/mnt/d/AI_Models/bge-m3"

model = BGEM3FlagModel(
    MODEL_PATH,
    use_fp16=False,
    device="cpu",
)

vector_store = VectorStore()


# =========================
# Embedding
# =========================

def get_embedding(text: str):
    """使用本地 BGE-M3 模型生成 embedding"""
    if not text or len(text.strip()) < 5:
        return None

    try:
        result = model.encode(text)

        if isinstance(result, dict):
            embedding = result.get('dense_vecs')
        else:
            embedding = result

        if hasattr(embedding, 'tolist'):
            embedding = embedding.tolist()

        if not isinstance(embedding, list):
            embedding = list(embedding)

        return embedding
    except Exception as e:
        print(f"❌ Embedding 生成失败: {e}")
        return None


# =========================
# 搜索相似新闻
# =========================

def find_similar_news(
    news_id: int,
    embedding_text: str,
    top_k: int = 5,
):

    embedding = get_embedding(
        embedding_text
    )

    result = vector_store.search_similar(
        embedding=embedding,
        top_k=top_k + 1,
    )

    ids = result["ids"][0]
    distances = result["distances"][0]
    documents = result["documents"][0]
    metadatas = result["metadatas"][0]

    similar_news = []

    for i in range(len(ids)):

        candidate_id = int(ids[i])

        # 排除自己
        if candidate_id == news_id:
            continue

        # Chroma cosine distance
        distance = distances[i]

        # cosine similarity
        similarity = 1 - distance

        similar_news.append({
            "news_id": candidate_id,
            "similarity": similarity,
            "document": documents[i],
            "metadata": metadatas[i],
        })

    return similar_news[:top_k]


# =========================
# 判断是否可能是重复事件
# =========================

def classify_similarity(similarity: float):

    if similarity >= 0.90:
        return "high"

    elif similarity >= 0.80:
        return "medium"

    else:
        return "low"


# =========================
# 测试
# =========================

if __name__ == "__main__":

    test_text = """
    OpenAI正式发布GPT-5，
    新模型在推理、代码和Agent能力方面进行了升级。
    """

    results = find_similar_news(
        news_id=-1,
        embedding_text=test_text,
        top_k=5,
    )

    for item in results:

        print(
            f"news_id={item['news_id']} "
            f"similarity={item['similarity']:.4f} "
            f"level={classify_similarity(item['similarity'])}"
        )