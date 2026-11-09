#直接从 SQLite 读取发布时间，然后更新 Chroma metadata。

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from embedding.vector_store import get_vector_store
from storage.db import get_connection
from datetime import datetime

store = get_vector_store()
conn = get_connection(row_factory=True)

collection = store.collection

try:
    result = collection.get(
        include=["metadatas"]
    )

    ids = result["ids"]
    metadatas = result["metadatas"]

    updated = 0
    missing = 0

    for i in range(0, len(ids), 500):
        batch_ids = ids[i:i + 500]
        batch_meta = metadatas[i:i + 500]

        news_ids = [int(x) for x in batch_ids]

        placeholders = ",".join("?" for _ in news_ids)

        rows = conn.execute(
            f"""
            SELECT id, published_ts
            FROM news
            WHERE id IN ({placeholders})
            """,
            news_ids,
        ).fetchall()

        ts_map = {
            int(row["id"]): row["published_ts"]
            for row in rows
        }

        update_ids = []
        update_metadatas = []

        for vector_id, metadata in zip(batch_ids, batch_meta):
            news_id = int(vector_id)
            published_ts = ts_map.get(news_id)

            if published_ts is None:
                missing += 1
                continue

            new_meta = dict(metadata or {})
            new_meta["news_id"] = news_id
            new_meta["published_ts"] = int(published_ts)

            update_ids.append(vector_id)
            update_metadatas.append(new_meta)

        if update_ids:
            collection.update(
                ids=update_ids,
                metadatas=update_metadatas,
            )

            updated += len(update_ids)

        print(
            f"处理进度：{min(i + 500, len(ids))}/{len(ids)}"
        )

    print("\n补齐完成")
    print(f"Chroma 总记录：{len(ids)}")
    print(f"成功更新：{updated}")
    print(f"缺少 SQLite 时间戳：{missing}")

finally:
    conn.close()