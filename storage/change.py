import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 每条新闻最近邻相似度的分位数，用来判断 EVENT_THRESHOLD=0.75 是否太严
import numpy as np
from pipeline.utils import day_bounds_ts
from storage.db import get_connection
from embedding.vector_store import get_vector_store

start, end = day_bounds_ts("2026-11-02")
conn = get_connection()
ids = [r[0] for r in conn.execute(
    "SELECT id FROM news WHERE published_ts>=? AND published_ts<? AND importance>3",
    (start, end))]
store = get_vector_store()
top = []
for i, e in store.get_embeddings(ids).items():
    r = store.collection.query(query_embeddings=[e], n_results=2)
    for sid, d in zip(r["ids"][0], r["distances"][0]):
        if int(sid) != i:
            top.append(1 - d)
            break
print(np.percentile(top, [10, 25, 50, 75, 90]))