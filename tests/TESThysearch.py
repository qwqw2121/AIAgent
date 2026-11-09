#测试检索效果，时间窗口
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrieval.hybrid_search import hybrid_search

from retrieval.hybrid_search import hybrid_search

queries = [
    "最近一周强化学习新闻",
    "最近一个月强化学习新闻",
    "最近一周大模型新闻",
    "强化学习",
]

for query in queries:
    print(f"\n{'=' * 60}")
    print("查询：", query)

    results = hybrid_search(query=query, limit=5)

    for item in results:
        print(
            item["news_id"],
            item["title"],
            item["published"],
            item["time_scope"],
        )