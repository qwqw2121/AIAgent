# eval/run_eval.py
"""
评测脚本（路由准确率 + 检索命中率 + 引用忠实度）
运行: python eval/run_eval.py
输出: 三个指标 + Langfuse score 上报
"""
import asyncio
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.graph import supervisor, kb_retrieve, build_graph, init_agent, TOOL_MAP, parse_mcp_result

# ---------- 测试集 ----------
TEST_CASES = [
    # (问题, 期望route, 期望report_date或None)
    ("最近有哪些大模型发布的新闻？", "knowledge", None),
    ("帮我总结一下昨天的重要新闻", "summarizer", "auto_yesterday"),
    ("今天有什么重要新闻", "summarizer", "auto_today"),
    ("帮我总结一下 2026-09-10 的新闻", "summarizer", "2026-09-10"),
    ("AI 芯片行业最近有什么动态？", "knowledge", None),
    ("帮我汇总今天的科技资讯", "summarizer", "auto_today"),
    ("量子计算有什么新进展？", "knowledge", None),
    ("把昨天的新闻整理成简报", "summarizer", "auto_yesterday"),
    ("OpenAI 最近发布了什么？", "knowledge", None),
    ("生成一份今天的日报", "summarizer", "auto_today"),
    # ... 补到 20+ 条，故意加几条边界case：
    ("今天的大模型新闻有哪些？", "knowledge", "auto_today"),  # 带日期但意图是检索，看你设计
    ("总结一下新闻", "summarizer", None),  # 无日期，应被拒绝
]

async def eval_router():
    from datetime import date, timedelta
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    correct = 0
    rows = []
    for q, expect_route, expect_date in TEST_CASES:
        state = {"question": q}
        out = await supervisor(state)
        real_date = {"auto_today": today, "auto_yesterday": yesterday}.get(expect_date, expect_date)
        ok_route = out["route"] == expect_route
        ok_date = (real_date is None) or (out["report_date"] == real_date)
        ok = ok_route and ok_date
        correct += ok
        rows.append({"q": q, "expect": expect_route, "got": out["route"], "ok": ok})
    acc = correct / len(TEST_CASES)
    print(f"\n📊 路由准确率: {correct}/{len(TEST_CASES)} = {acc:.1%}")
    for r in rows:
        if not r["ok"]:
            print(f"  ❌ {r['q']} | expect={r['expect']} got={r['got']}")
    return acc

async def eval_retrieval(n_questions=8):
    """检索命中率: 检索结果非空 + 人工抽查相关性"""
    questions = [q for q, r, _ in TEST_CASES if r == "knowledge"][:n_questions]
    hit = 0
    for q in questions:
        out = await kb_retrieve({"question": q})
        if out["docs"]:
            hit += 1
    rate = hit / len(questions)
    print(f"📊 检索命中率(非空): {hit}/{len(questions)} = {rate:.1%}")
    # 相关性需要人工抽查：打印出来看，然后在 Langfuse 打 relevance score
    return rate

def eval_citation_faithfulness(answer: str, docs: list) -> bool:
    """引用忠实度: 回答里的[序号]是否都有对应文档（粗检）"""
    cited = set(re.findall(r"\[(\d+)\]", answer))
    valid = {str(i) for i in range(1, len(docs) + 1)}
    return cited.issubset(valid) if cited else False

async def main():
    await init_agent()  # 加载 MCP 工具
    await eval_router()
    await eval_retrieval()

    # 端到端跑一条，演示引用忠实度检查
    app = build_graph()
    r = await app.ainvoke({"question": "最近有哪些大模型发布的新闻？"})
    faithful = eval_citation_faithfulness(r["answer"], [{}] * 5)
    print(f"📊 引用忠实度(样例): {'通过' if faithful else '存在悬空引用'}")

if __name__ == "__main__":
    asyncio.run(main())