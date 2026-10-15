# eval/run_eval.py
"""
评测脚本（适配「单 Agent + 工具分组」架构）

用法:
  python eval/run_eval.py agent                 # 工具选择准确率 / Tool 成功率 / 延迟 P50·P95 / 引用有效率
  python eval/run_eval.py retrieval             # 检索 Top5 命中率 + MRR
  python eval/run_eval.py load -c 5 -n 20       # 并发压测：并发 c，共 n 次请求
  python eval/run_eval.py export -n 100         # 随机导出 100 条关键事件，供人工标注
  python eval/run_eval.py score eval/label.csv  # 读取人工标注，输出准确率及 95% 置信区间

人工标注口径（label 列填 1 / 0）:
  1 = 事件真实存在，表述与原始新闻一致，无编造
  0 = 事实错误 / 编造 / 重复事件 / 无意义

注意:
  - 评测期间会把「日报后台生成」替换成空实现，避免误触发耗时的 daily_flow。
  - REPORT_DATE 必须是库里已有日报的日期。
  - 需要改动的地方都标了 TODO。
"""
import argparse
import asyncio
import csv
import importlib
import json
import os
import random
import re
import statistics
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

AGENT_MODULE = "agent.graph"      # TODO: 你的 Agent 文件所在模块
REPORT_DATE = "2026-10-08"        # TODO: 库里已存在日报的日期
OUT_PATH = os.path.join(ROOT, "eval", "results.json")

# ---------------------------------------------------------------
# 测试集：expect = 期望至少调用的工具集合；空集合表示不应调用任何工具
# TODO: 补到 30 条左右，并保留几条边界 case
# ---------------------------------------------------------------
CASES = [
    {"q": "最近有哪些大模型发布的新闻？", "expect": {"search_news_semantic"}},
    {"q": "AI 芯片行业最近有什么动态？", "expect": {"search_news_semantic"}},
    {"q": "量子计算有什么新进展？", "expect": {"search_news_semantic"}},
    {"q": "OpenAI 最近发布了什么？", "expect": {"search_news_semantic"}},
    {"q": "今天的大模型新闻有哪些？", "expect": {"search_news_semantic"}},  # 边界：带日期词但意图是检索
    {"q": f"帮我总结一下 {REPORT_DATE} 的新闻", "expect": {"get_daily_report"}},
    {"q": f"把 {REPORT_DATE} 的新闻整理成简报", "expect": {"get_daily_report"}},
    {"q": f"先看 {REPORT_DATE} 的日报，再查一下 AI 芯片的最新进展",
     "expect": {"get_daily_report", "search_news_semantic"}},               # 跨组并行
    {"q": "你好，你能做什么？", "expect": set()},                           # 不应调工具
]

# 检索集：Top5 任一文档命中任一关键词即算命中（关键词要有区分度，避免虚高）
# TODO: 按你库里的真实内容改写，建议 20 条以上
RETRIEVAL_SET = [
    {"q": "最近有哪些大模型发布的新闻？", "keywords": ["大模型", "GPT", "Claude", "Gemini", "DeepSeek", "Qwen"]},
    {"q": "AI 芯片行业最近有什么动态？", "keywords": ["芯片", "英伟达", "NVIDIA", "GPU", "算力"]},
    {"q": "量子计算有什么新进展？", "keywords": ["量子"]},
    {"q": "OpenAI 最近发布了什么？", "keywords": ["OpenAI"]},
]

# TODO: 按你实际的「关键事件」表结构修改
EVENTS_SQL = "SELECT id, event_name, summary FROM events ORDER BY RANDOM() LIMIT ?"


# ---------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------
def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return 0.0
    return xs[min(len(xs) - 1, max(0, round(p / 100 * (len(xs) - 1))))]


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (c - m) / d, (c + m) / d


def count_results(content) -> int:
    """估算语义检索返回的条数（FastMCP 的 list 返回通常被拆成多个 content block）"""
    if isinstance(content, list):
        return len(content)
    try:
        data = json.loads(content)
        return len(data) if isinstance(data, list) else 1
    except Exception:
        return 1 if content else 0


def analyse(msgs):
    from langchain_core.messages import AIMessage, ToolMessage

    called, id2name = [], {}
    tool_total = tool_fail = sem_n = 0
    for m in msgs:
        if isinstance(m, AIMessage):
            for c in m.tool_calls or []:
                called.append(c["name"])
                id2name[c["id"]] = c["name"]
        elif isinstance(m, ToolMessage):
            tool_total += 1
            text = m.content if isinstance(m.content, str) else json.dumps(m.content, ensure_ascii=False)
            if getattr(m, "status", "success") == "error" or "执行超时" in text:
                tool_fail += 1
            elif id2name.get(m.tool_call_id) == "search_news_semantic":
                sem_n += count_results(m.content)

    answer = msgs[-1].content if msgs else ""
    if not isinstance(answer, str):
        answer = json.dumps(answer, ensure_ascii=False)
    cited = {int(x) for x in re.findall(r"\[(\d+)\]", answer)}
    cite_ok = None
    if sem_n:  # 只在调用过语义检索时评估引用有效性
        cite_ok = bool(cited) and min(cited) >= 1 and max(cited) <= sem_n
    return {"called": called, "tool_total": tool_total, "tool_fail": tool_fail,
            "cite_ok": cite_ok, "answer": answer}


async def load_app():
    G = importlib.import_module(AGENT_MODULE)

    async def _no_generate(report_date, force=False):  # 评测时禁止真实触发日报生成
        return f"[eval] 已跳过真实生成 {report_date}"

    G.trigger_report_generation = _no_generate
    return await G.init_agent()


async def run_one(app, q, timeout=120):
    from langchain_core.messages import HumanMessage

    cfg = {"configurable": {"thread_id": f"eval-{uuid.uuid4().hex[:8]}"}, "recursion_limit": 15}
    t0, err, res = time.perf_counter(), None, {}
    try:
        r = await asyncio.wait_for(app.ainvoke({"messages": [HumanMessage(content=q)]}, config=cfg), timeout)
        res = analyse(r["messages"])
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    return {"q": q, "latency": time.perf_counter() - t0, "error": err, **res}


# ---------------------------------------------------------------
# 1) Agent 端到端
# ---------------------------------------------------------------
async def eval_agent():
    app = await load_app()
    rows = []
    for c in CASES:
        r = await run_one(app, c["q"])
        called = set(r.get("called", []))
        forbid = c.get("forbid", set())
        r["tool_ok"] = (((not called) if not c["expect"] else c["expect"].issubset(called))
                and not (forbid & called))
        # r["tool_ok"] = (not called) if not c["expect"] else c["expect"].issubset(called)
        if r["error"]:
            r["tool_ok"] = False
        rows.append(r)
        print(f"{'✅' if r['tool_ok'] else '❌'} {c['q']} | 期望={sorted(c['expect'])} 实际={sorted(called)} | {r['latency']:.1f}s")
        if r["error"]:
            print("   错误:", r["error"])

    n = len(rows)
    lat = [r["latency"] for r in rows if not r["error"]]
    tt = sum(r.get("tool_total", 0) for r in rows)
    tf = sum(r.get("tool_fail", 0) for r in rows)
    cites = [r["cite_ok"] for r in rows if r.get("cite_ok") is not None]
    summary = {
        "n_cases": n,
        "tool_selection_acc": sum(r["tool_ok"] for r in rows) / n,
        "completion_rate": sum(1 for r in rows if not r["error"]) / n,
        "tool_call_success_rate": (1 - tf / tt) if tt else None,
        "latency_avg": statistics.mean(lat) if lat else None,
        "latency_p50": pct(lat, 50),
        "latency_p95": pct(lat, 95),
        "citation_valid_rate": (sum(cites) / len(cites)) if cites else None,
    }
    print("\n📊", json.dumps(summary, ensure_ascii=False, indent=2))
    _save({"agent": summary, "rows": [{k: v for k, v in r.items() if k != "answer"} for r in rows]})
    return summary


# ---------------------------------------------------------------
# 2) 检索 Top5 命中率
# ---------------------------------------------------------------
def eval_retrieval(k=5):
    from storage.vectorstore import get_retriever

    retriever = get_retriever()
    hit, rr = 0, []
    for item in RETRIEVAL_SET:
        docs = retriever.invoke(item["q"])[:k]
        rank = None
        for i, d in enumerate(docs, 1):
            text = (d.page_content + str(d.metadata.get("title", ""))).lower()
            if any(kw.lower() in text for kw in item["keywords"]):
                rank = i
                break
        hit += rank is not None
        rr.append(1 / rank if rank else 0)
        print(f"{'✅' if rank else '❌'} {item['q']} | 首个命中排名={rank}")
    n = len(RETRIEVAL_SET)
    summary = {"n": n, f"top{k}_hit_rate": hit / n, "mrr": sum(rr) / n}
    print("\n📊", summary, "\n（口径：关键词命中；建议再人工抽查 10 条的相关性）")
    _save({"retrieval": summary})


# ---------------------------------------------------------------
# 3) 并发压测
# ---------------------------------------------------------------
async def eval_load(concurrency, total):
    app = await load_app()
    qs = [random.choice(CASES)["q"] for _ in range(total)]
    sem = asyncio.Semaphore(concurrency)

    async def worker(q):
        async with sem:
            return await run_one(app, q)

    t0 = time.perf_counter()
    rows = await asyncio.gather(*(worker(q) for q in qs))
    wall = time.perf_counter() - t0
    lat = [r["latency"] for r in rows if not r["error"]]
    summary = {
        "concurrency": concurrency, "total": total,
        "success_rate": len(lat) / total,
        "p50": pct(lat, 50), "p95": pct(lat, 95),
        "throughput_qps": total / wall,
    }
    print("\n📊", json.dumps(summary, ensure_ascii=False, indent=2),
          "\n（受 LLM 接口限流影响，结果代表「端到端」而非服务本身上限）")
    _save({"load": summary})


# ---------------------------------------------------------------
# 4) 人工抽检：导出 / 计分
# ---------------------------------------------------------------
def export_events(n, path):
    from storage.db import get_connection

    conn = get_connection()
    try:
        rows = conn.execute(EVENTS_SQL, (n,)).fetchall()
    finally:
        conn.close()
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "title", "summary", "label(1对/0错)", "note"])
        for r in rows:
            w.writerow([*tuple(r)[:3], "", ""])
    print(f"✅ 已导出 {len(rows)} 条 → {path}，请在 label 列填 1/0 后运行 score")


def score_labels(path):
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    labels = [r["label(1对/0错)"].strip() for r in rows if r["label(1对/0错)"].strip() in ("0", "1")]
    n, k = len(labels), sum(1 for x in labels if x == "1")
    lo, hi = wilson(k, n)
    print(f"📊 人工抽检准确率: {k}/{n} = {k / n:.1%}（95% 区间 {lo:.1%} ~ {hi:.1%}）")
    _save({"event_accuracy": {"n": n, "correct": k, "acc": k / n, "ci95": [lo, hi]}})


def _save(obj):
    data = {}
    if os.path.exists(OUT_PATH):
        try:
            data = json.load(open(OUT_PATH, encoding="utf-8"))
        except Exception:
            pass
    data.update(obj)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    json.dump(data, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("agent")
    sub.add_parser("retrieval")
    p = sub.add_parser("load"); p.add_argument("-c", type=int, default=5); p.add_argument("-n", type=int, default=20)
    p = sub.add_parser("export"); p.add_argument("-n", type=int, default=100); p.add_argument("-o", default="eval/label.csv")
    p = sub.add_parser("score"); p.add_argument("path")
    a = ap.parse_args()

    if a.cmd == "agent":
        asyncio.run(eval_agent())
    elif a.cmd == "retrieval":
        eval_retrieval()
    elif a.cmd == "load":
        asyncio.run(eval_load(a.c, a.n))
    elif a.cmd == "export":
        export_events(a.n, a.o)
    elif a.cmd == "score":
        score_labels(a.path)