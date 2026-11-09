# tests/test_hybrid_search.py
"""
hybrid_search 链路测试脚本。

运行（必须在项目根目录）：
    cd ~/project/ai-news-agent
    PYTHONPATH=. python tests/test_hybrid_search.py

前置条件：
    - .env 里配好 LLM_API_KEY（若开启 rerank）
    - 向量库和 SQLite 已有数据
"""

import sys
import time
from pathlib import Path

# 让脚本无论从哪运行都能找到项目包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.hybrid_search import hybrid_search, warmup
from retrieval import reranker


def sep(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def show_results(results: list[dict]):
    if not results:
        print("  (无结果)")
        return
    for i, r in enumerate(results, 1):
        print(f"  [{i}] id={r.get('news_id')} scope={r.get('time_scope')}")
        print(f"      title: {r.get('title')}")
        print(f"      source: {r.get('source')} | published: {r.get('published')}")
        print(f"      category: {r.get('category')} | importance: {r.get('importance')}")
        snippet = (r.get("summary") or "")[:80]
        print(f"      summary: {snippet}...")


def case_basic():
    sep("用例 1：基础检索（无时间过滤）")
    t0 = time.perf_counter()
    results = hybrid_search(query="人工智能", limit=5)
    print(f"  耗时 {time.perf_counter() - t0:.2f}s，返回 {len(results)} 条")
    show_results(results)
    assert len(results) <= 5, "limit 未生效"
    return results


def case_time_filter():
    sep("用例 2：带时间过滤的检索")
    t0 = time.perf_counter()
    results = hybrid_search(query="最近一周的 AI 新闻", limit=5)
    print(f"  耗时 {time.perf_counter() - t0:.2f}s，返回 {len(results)} 条")
    show_results(results)
    scopes = {r.get("time_scope") for r in results}
    print(f"  出现的 time_scope: {scopes}")
    return results


def case_rerank_off():
    sep("用例 3：关闭精排（use_rerank=False）")
    t0 = time.perf_counter()
    results = hybrid_search(query="大模型", limit=5, use_rerank=False)
    print(f"  耗时 {time.perf_counter() - t0:.2f}s，返回 {len(results)} 条")
    show_results(results)
    return results


def case_rerank_status():
    sep("用例 4：精排开关状态检查")
    print(f"  reranker.is_enabled() = {reranker.is_enabled()}")
    if reranker.is_enabled():
        print(f"  RERANK_BACKEND = {reranker.RERANK_BACKEND}")
        print(f"  RERANK_MODEL   = {reranker.RERANK_MODEL}")
        print(f"  API_KEY 是否配置 = {bool(reranker.API_KEY)}")
    else:
        print("  提示：RERANK_ENABLED 未开启，精排会被跳过")


def case_empty_query():
    sep("用例 5：空查询（应走按时间直查分支）")
    t0 = time.perf_counter()
    results = hybrid_search(query="", limit=3)
    print(f"  耗时 {time.perf_counter() - t0:.2f}s，返回 {len(results)} 条")
    show_results(results)
    return results


def case_category_filter():
    sep("用例 6：分类过滤")
    results = hybrid_search(query="AI", category="科技", limit=3)
    print(f"  返回 {len(results)} 条")
    show_results(results)
    for r in results:
        assert r.get("category") == "产品发布", f"分类过滤失效: {r.get('category')}"
    return results


def case_importance_filter():
    sep("用例 7：重要性过滤（min_importance=3）")
    results = hybrid_search(query="AI", limit=5, min_importance=3)
    print(f"  返回 {len(results)} 条")
    show_results(results)
    for r in results:
        assert (r.get("importance") or 0) >= 3, f"重要性过滤失效: {r.get('importance')}"
    return results


def case_limit_bound():
    sep("用例 8：limit 边界（传 100，应被截到 MAX_LIMIT=8）")
    results = hybrid_search(query="AI", limit=100)
    print(f"  返回 {len(results)} 条（期望 <= 8）")
    assert len(results) <= 8, "MAX_LIMIT 未生效"
    return results


def main():
    print("hybrid_search 链路测试开始")
    print(f"Python: {sys.version.split()[0]}")

    # 预热：向量库 + 重排模型（可选）
    sep("预热")
    t0 = time.perf_counter()
    warmup()
    print(f"  预热耗时 {time.perf_counter() - t0:.1f}s")

    case_rerank_status()

    failures = []
    for name, fn in [
        ("基础检索", case_basic),
        ("时间过滤", case_time_filter),
        ("关闭精排", case_rerank_off),
        ("空查询", case_empty_query),
        ("分类过滤", case_category_filter),
        ("重要性过滤", case_importance_filter),
        ("limit 边界", case_limit_bound),
    ]:
        try:
            fn()
        except AssertionError as e:
            failures.append((name, f"断言失败: {e}"))
            print(f"  ❌ {name} 断言失败: {e}")
        except Exception as e:
            failures.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ❌ {name} 异常: {type(e).__name__}: {e}")

    sep("汇总")
    if failures:
        print(f"❌ {len(failures)} 个用例失败：")
        for name, err in failures:
            print(f"   - {name}: {err}")
        sys.exit(1)
    else:
        print("✅ 全部用例通过")


if __name__ == "__main__":
    main()