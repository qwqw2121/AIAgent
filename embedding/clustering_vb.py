''' ④事件聚类
大量新闻 → 自动形成事件簇
存入events数据表
'''

# embedding/clustering.py

import numpy as np

from sklearn.cluster import DBSCAN

from  embedding.vector_store import VectorStore


# =========================
# 配置
# =========================

vector_store = VectorStore()

# cosine distance
# 例如：
# similarity = 0.90
# distance = 0.10
#
# 所以：
# eps = 0.10
EPS = 0.10

MIN_SAMPLES = 2


# =========================
# 获取所有新闻向量
# =========================

def load_embeddings():

    result = vector_store.get_all()

    ids = result["ids"]
    embeddings = result["embeddings"]
    metadatas = result["metadatas"]

    return (
        ids,
        np.array(embeddings),
        metadatas,
    )


# =========================
# 聚类
# =========================

def cluster_news():

    ids, embeddings, metadatas = load_embeddings()

    if len(embeddings) == 0:

        print("向量数据库为空")

        return []

    print(
        f"新闻数量：{len(embeddings)}"
    )

    # =========================
    # DBSCAN
    # =========================

    clustering = DBSCAN(
        eps=EPS,
        min_samples=MIN_SAMPLES,
        metric="cosine",
    )

    labels = clustering.fit_predict(
        embeddings
    )

    # =========================
    # 整理结果
    # =========================

    clusters = {}

    for news_id, label, metadata in zip(
        ids,
        labels,
        metadatas,
    ):

        # -1代表噪声
        if label == -1:
            continue

        if label not in clusters:
            clusters[label] = []

        clusters[label].append({
            "news_id": news_id,
            "title": metadata.get(
                "title", ""
            ),
        })

    return clusters


# =========================
# 打印结果
# =========================

def main():

    clusters = cluster_news()

    print(
        f"\n发现 {len(clusters)} 个事件簇\n"
    )

    for cluster_id, news_list in clusters.items():

        print(
            f"========== Event {cluster_id} =========="
        )

        for news in news_list:

            print(
                f"{news['news_id']} "
                f"{news['title']}"
            )

        print()


if __name__ == "__main__":
    main()