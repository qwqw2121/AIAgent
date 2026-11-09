import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.query_parser import parse_query
from retrieval.hybrid_search import hybrid_search

# 1. 测试时间解析
queries = [
    "获取当月 AI 新闻",
    "最近7天的大模型新闻",
    "2026年10月的 OpenAI 新闻",
    "昨天的 AI 新闻",
]

for q in queries:
    print(q, "=>", parse_query(q))


# 2. 测试实际检索
results = hybrid_search(
    query="获取当月 AI 新闻",
    limit=8,
    use_rerank=False,
)

for item in results:
    print(
        item["published"],
        item["title"],
        item["news_id"],
    )