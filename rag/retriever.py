# rag/retriever.py

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / "embedding"))

from sentence_transformers import SentenceTransformer
from vector_store import VectorStore

# ============================================================
# 配置
# ============================================================

MODEL_PATH = "/mnt/d/AI_Models/bge-m3"
DEVICE = "cpu"
TOP_K = 5

# ============================================================
# Embedding Model
# ============================================================

model = SentenceTransformer(MODEL_PATH, device=DEVICE)

# ============================================================
# Vector Store
# ============================================================

vector_store = VectorStore()

# ============================================================
# Retriever
# ============================================================

def retrieve(query, top_k=TOP_K):
    # Query Embedding
    query_embedding = model.encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=False
    )[0].tolist()
    
    # Chroma Search
    results = vector_store.collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )
    
    documents = results["documents"][0]
    distances = results["distances"][0]
    ids = results["ids"][0]
    
    return [
        {
            "news_id": int(news_id),
            "text": document,
            "distance": distance,
            "similarity": 1 - distance
        }
        for news_id, document, distance in zip(ids, documents, distances)
    ]

# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    query = input("请输入问题：")
    results = retrieve(query)
    
    print()
    for i, result in enumerate(results, start=1):
        print(f"===== {i} =====")
        print(f"news_id: {result['news_id']}")
        print(f"similarity: {result['similarity']:.4f}")
        print(result["text"])
        print()