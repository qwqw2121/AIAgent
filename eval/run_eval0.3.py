# eval/run_eval0.3.py
"""
评测脚本 v0.3（适配「单 Agent + 工具分组」架构）

用法:
  python eval/run_eval0.3.py agent --repeat 3   # 30 条用例 × 3 次：工具选择 / 参数 / 回答 / 延迟 / 分类统计
  python eval/run_eval0.3.py retrieval          # 检索 Top5 命中率 + MRR，并探测「无结果」查询是否仍返回文档
  python eval/run_eval0.3.py load -c 5 -n 20    # 并发压测（只用单轮用例）
  python eval/run_eval0.3.py score eval/label_report.csv   # 读取人工标注（由 export_report_events.py 导出）

判定规则（每条用例）:
  expect          必须调用的工具；空集合 = 不应调用任何工具
  forbid          禁止调用的工具（用来抓「过度调用」）
  expect_args     指定工具的参数必须匹配（如 force=True）
  contains        回答中至少包含其中一个关键词（用于「无结果要如实说明」）
  turns           多轮用例：同一 thread_id 依次提问，只评判最后一轮

注意:
  - 评测期间「日报后台生成」被替换为模拟实现，不会真正启动 daily_flow；
    是否请求生成、force 参数，以模型发出的 tool_call 为准。
  - REPORT_DATE 必须是库里已有日报的日期；MISSING_DATE 必须是确定不存在的日期。
  - 多轮用例依赖 Checkpointer；若 Checkpointer 初始化失败（无记忆模式），这两条会失败。
  - date_search 类用例只验证「选对了检索工具」：现有检索工具没有日期过滤参数，不能据此声称日期条件被满足。
  - 无结果回答采用关键词校验，失败时请人工看一眼回答，可能只是措辞不同。
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
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

AGENT_MODULE = "agent.graph"      # TODO: 你的 Agent 文件所在模块
REPORT_DATE = "2026-10-08"        # TODO: 库里已存在日报的日期
MISSING_DATE = "2099-01-01"       # 确定不存在日报的日期
OUT_PATH = os.path.join(ROOT, "eval", "results.json")

NOT_FOUND = ["没有找到", "未找到", "没有检索到", "未检索到", "暂无相关", "没有相关", "没有发现", "未发现"]
NO_GEN = {"request_daily_report"}
NO_REPORT = {"get_daily_report", "request_daily_report"}
SEM, SRCH, GET, REQ = "search_news_semantic", "search_news", "get_daily_report", "request_daily_report"


def C(q, expect=(), cat="other", forbid=(), args=None, contains=None, turns=None):
    return {"q": q, "turns": turns or [q], "expect": set(expect), "cat": cat,
            "forbid": set(forbid), "expect_args": args or {}, "contains": contains}


# ---------------------------------------------------------------
# 测试集（30 条，8 类）
# ---------------------------------------------------------------
CASES = [
    # 语义检索 + 边界意图
    C("最近有哪些大模型发布的新闻？", {SEM}, "semantic"),
    C("AI 芯片行业最近有什么动态？", {SEM}, "semantic"),
    C("量子计算有什么新进展？", {SEM}, "semantic"),
    C("OpenAI 最近发布了什么？", {SEM}, "semantic"),
    C("今天的大模型新闻有哪些？", {SEM}, "boundary", forbid=NO_REPORT),  # “今天”不等于读日报

    # 带日期的检索问题（只验证工具选择，检索工具本身没有日期过滤）
    C("查一下 2026-10-08 发布的 AI 芯片相关新闻", {SEM}, "date_search", forbid=NO_GEN),
    C("2026 年 10 月 8 日有哪些关于 OpenAI 的新闻？", {SEM}, "date_search", forbid=NO_GEN),
    C("帮我检索 2026-10-08 到 2026-10-10 的大模型新闻", {SEM}, "date_search", forbid=NO_GEN),
    C("截至 2026-10-08，DeepSeek 有哪些相关动态？", {SEM}, "date_search", forbid=NO_GEN),
    C("找出 2026-10-08 那天有关 GPU 的报道，不要日报总结", {SEM}, "date_search", forbid=NO_REPORT),
    C("2026-10-08 的新闻里，有没有关于多模态模型的内容？", {SEM}, "date_search", forbid=NO_GEN),

    # 已有日报读取 / 组合
    C(f"帮我总结一下 {REPORT_DATE} 的新闻", {GET}, "report_read", forbid=NO_GEN),
    C(f"把 {REPORT_DATE} 的新闻整理成简报", {GET}, "report_read", forbid=NO_GEN),
    C(f"读取 {REPORT_DATE} 的日报，列出最重要的三条", {GET}, "report_read", forbid=NO_GEN),
    C(f"先看 {REPORT_DATE} 的日报，再查一下 AI 芯片的最新进展", {GET, SEM}, "report_read", forbid=NO_GEN),
    C(f"请读取 {REPORT_DATE} 已经生成的日报，不要重新生成", {GET}, "report_read", forbid=NO_GEN),

    # 日报不存在 → 应请求生成（评测中生成函数被 mock）
    C(f"请生成 {MISSING_DATE} 的日报", {REQ}, "report_generate"),
    C(f"我需要 {MISSING_DATE} 的 AI 新闻简报，如果还没有就发起生成", {REQ}, "report_generate"),
    C(f"{MISSING_DATE} 的日报有吗？没有的话请生成一份", {GET, REQ}, "report_generate"),
    C(f"检查 {MISSING_DATE} 的日报状态，缺失就创建", {GET, REQ}, "report_generate"),

    # 强制重新生成 → force=True（题面不出现参数名，避免泄题）
    C(f"强制重新生成 {REPORT_DATE} 的日报", {REQ}, "force", args={REQ: {"force": True}}),
    C(f"忽略已有的 {REPORT_DATE} 日报，重新生成一份最新版本", {REQ}, "force", args={REQ: {"force": True}}),

    # 库里大概率没有的话题 → 应如实说明
    C("检索数据库中关于火星城市地下海洋 AI 监管政策的新闻", {SEM}, "no_result", contains=NOT_FOUND),
    C("新闻库里有没有关于 2099 年月球宠物经济监管的报道？", {SEM}, "no_result", contains=NOT_FOUND),
    C("只根据新闻库回答：最近有哪些关于海底城市 AI 选举系统的新闻？如果没有请直说",
      {SEM}, "no_result", contains=NOT_FOUND),

    # 不应调用工具
    C("你好，你能做什么？", set(), "no_tool"),
    C("帮我写一首关于春天的短诗", set(), "no_tool"),
    C("1+1 等于几？", set(), "no_tool"),

    # 多轮记忆（同一 thread_id；只评判最后一轮）
    C("我刚才说我关注什么主题？", set(), "multi_turn", contains=["量子"],
      turns=["我最近在关注量子计算这个主题。", "我刚才说我关注什么主题？"]),
    C("我刚才提到的是哪一天？", set(), "multi_turn", contains=["10-08", "10 月 8", "10月8"],
      turns=[f"我想聊聊 {REPORT_DATE} 这一天。", "我刚才提到的是哪一天？"]),
]

# 检索集：Top5 任一文档命中任一关键词即算命中（关键词要有区分度，避免虚高）
# TODO: 按你库里的真实内容改写，建议 20 条以上
RETRIEVAL_SET = [
    {"q": "最近有哪些大模型发布的新闻？", "keywords": ["大模型", "GPT", "Claude", "Gemini", "DeepSeek", "Qwen"]},
    {"q": "AI 芯片行业最近有什么动态？", "keywords": ["芯片", "英伟达", "NVIDIA", "GPU", "算力"]},
    {"q": "量子计算有什么新进展？", "keywords": ["量子"]},
    {"q": "OpenAI 最近发布了什么？", "keywords": ["OpenAI"]},
]
NO_RESULT_QUERIES = ["火星城市地下海洋 AI 监管政策", "2099 年月球宠物经济监管", "海底城市 AI 选举系统"]


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
    if isinstance(content, list):
        return len(content)
    try:
        data = json.loads(content)
        return len(data) if isinstance(data, list) else 1
    except Exception:
        return 1 if content else 0


EMPTY = {"called": [], "calls": [], "tool_total": 0, "tool_fail": 0, "cite_ok": None, "answer": ""}


def analyse(msgs):
    """只分析最后一轮（最后一条 HumanMessage 之后的消息）"""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    idx = max((i for i, m in enumerate(msgs) if isinstance(m, HumanMessage)), default=-1)
    msgs = msgs[idx + 1:]

    calls, id2name = [], {}
    tool_total = tool_fail = sem_n = 0
    for m in msgs:
        if isinstance(m, AIMessage):
            for c in m.tool_calls or []:
                calls.append((c["name"], c.get("args") or {}))
                id2name[c["id"]] = c["name"]
        elif isinstance(m, ToolMessage):
            tool_total += 1
            text = m.content if isinstance(m.content, str) else json.dumps(m.content, ensure_ascii=False)
            if getattr(m, "status", "success") == "error" or "执行超时" in text:
                tool_fail += 1
            elif id2name.get(m.tool_call_id) == SEM:
                sem_n += count_results(m.content)

    answer = msgs[-1].content if msgs else ""
    if not isinstance(answer, str):
        answer = json.dumps(answer, ensure_ascii=False)
    cited = {int(x) for x in re.findall(r"\[(\d+)\]", answer)}
    cite_ok = (bool(cited) and min(cited) >= 1 and max(cited) <= sem_n) if sem_n else None
    return {"called": [n for n, _ in calls], "calls": calls, "tool_total": tool_total,
            "tool_fail": tool_fail, "cite_ok": cite_ok, "answer": answer}


def check(c, r):
    """返回 (是否通过, 失败原因列表)"""
    if r["error"]:
        return False, [f"执行异常: {r['error']}"]
    why, called = [], set(r["called"])
    if c["expect"]:
        miss = c["expect"] - called
        if miss:
            why.append(f"缺少工具 {sorted(miss)}")
    elif called:
        why.append(f"不应调用工具，实际调用 {sorted(called)}")
    bad = c["forbid"] & called
    if bad:
        why.append(f"调用了禁用工具 {sorted(bad)}")
    for tool, want in c["expect_args"].items():
        got = [a for n, a in r["calls"] if n == tool]
        if not any(all(a.get(k) == v for k, v in want.items()) for a in got):
            why.append(f"{tool} 参数不符，期望 {want}，实际 {got}")
    if c["contains"] and not any(k in r["answer"] for k in c["contains"]):
        why.append(f"回答未包含期望关键词 {c['contains'][:3]}…（请人工看一眼回答）")
    return not why, why


async def load_app():
    G = importlib.import_module(AGENT_MODULE)

    async def _no_generate(report_date, force=False):  # 评测时禁止真实触发日报生成
        return f"[eval] 已跳过真实生成 {report_date}（force={force}）"

    G.trigger_report_generation = _no_generate
    return await G.init_agent()


async def run_one(app, turns, timeout=120):
    from langchain_core.messages import HumanMessage

    cfg = {"configurable": {"thread_id": f"eval-{uuid.uuid4().hex[:8]}"}, "recursion_limit": 15}
    err, res, t0, lat = None, dict(EMPTY), time.perf_counter(), 0.0
    try:
        for t in turns:
            t0 = time.perf_counter()
            r = await asyncio.wait_for(
                app.ainvoke({"messages": [HumanMessage(content=t)]}, config=cfg), timeout)
            lat = time.perf_counter() - t0
        res = analyse(r["messages"])
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        lat = time.perf_counter() - t0
    return {"turns": turns, "latency": lat, "error": err, **res}


# ---------------------------------------------------------------
# 1) Agent 端到端
# ---------------------------------------------------------------
async def eval_agent(repeat):
    app = await load_app()
    attempts, per_case = [], []
    for c in CASES:
        oks = []
        for k in range(repeat):
            r = await run_one(app, c["turns"])
            ok, why = check(c, r)
            oks.append(ok)
            attempts.append({"cat": c["cat"], "q": c["q"], "ok": ok, "why": why,
                             "called": sorted(set(r["called"])), "latency": r["latency"],
                             "error": r["error"], "tool_total": r["tool_total"],
                             "tool_fail": r["tool_fail"], "cite_ok": r["cite_ok"]})
            print(f"{'✅' if ok else '❌'} [{c['cat']}] {c['q']} ({k + 1}/{repeat}) "
                  f"| 实际={sorted(set(r['called']))} | {r['latency']:.1f}s")
            for w in why:
                print("   ↳", w)
        per_case.append(oks)

    n = len(attempts)
    passed = sum(a["ok"] for a in attempts)
    stable = sum(all(o) for o in per_case)
    lo, hi = wilson(stable, len(CASES))
    lat = [a["latency"] for a in attempts if not a["error"]]
    tt = sum(a["tool_total"] for a in attempts)
    tf = sum(a["tool_fail"] for a in attempts)

    by_cat, lat_cat = defaultdict(list), defaultdict(list)
    for a in attempts:
        by_cat[a["cat"]].append(a["ok"])
        if not a["error"]:
            lat_cat[a["cat"]].append(a["latency"])

    summary = {
        "n_cases": len(CASES), "repeat": repeat,
        "attempt_pass_rate": passed / n,
        "case_all_pass": f"{stable}/{len(CASES)}",
        "case_all_pass_ci95": [round(lo, 3), round(hi, 3)],
        "completion_rate": sum(1 for a in attempts if not a["error"]) / n,
        "tool_call_success_rate": (1 - tf / tt) if tt else None,
        "latency_avg": statistics.mean(lat) if lat else None,
        "latency_p50": pct(lat, 50), "latency_p95": pct(lat, 95),
        "by_category": {k: f"{sum(v)}/{len(v)}" for k, v in by_cat.items()},
        "latency_avg_by_category": {k: round(statistics.mean(v), 1) for k, v in lat_cat.items()},
    }
    print("\n📊", json.dumps(summary, ensure_ascii=False, indent=2))
    print("（no_tool 类的平均延迟约等于单次 LLM 调用基线；其余类别多出的部分来自工具调用与第二次 LLM 调用）")
    _save({"agent": summary, "attempts": attempts})
    return summary


# ---------------------------------------------------------------
# 2) 检索 Top5 命中率 + 无结果探测
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

    print("\n🔎 无结果探测：库里不存在的话题，检索器仍返回了几条？")
    counts = {}
    for q in NO_RESULT_QUERIES:
        counts[q] = len(retriever.invoke(q))
        print(f"  {q} -> {counts[q]} 条")
    print("  若都返回 top-k 条，说明检索器没有相似度阈值，Agent 拿不到「无结果」的明确信号。")
    _save({"retrieval": summary, "no_result_probe": counts})


# ---------------------------------------------------------------
# 3) 并发压测（只用单轮用例）
# ---------------------------------------------------------------
async def eval_load(concurrency, total):
    app = await load_app()
    pool = [c for c in CASES if len(c["turns"]) == 1]
    qs = [random.choice(pool)["turns"] for _ in range(total)]
    sem = asyncio.Semaphore(concurrency)

    async def worker(turns):
        async with sem:
            return await run_one(app, turns)

    t0 = time.perf_counter()
    rows = await asyncio.gather(*(worker(t) for t in qs))
    wall = time.perf_counter() - t0
    lat = [r["latency"] for r in rows if not r["error"]]
    summary = {"concurrency": concurrency, "total": total, "success_rate": len(lat) / total,
               "p50": pct(lat, 50), "p95": pct(lat, 95), "throughput_qps": total / wall}
    print("\n📊", json.dumps(summary, ensure_ascii=False, indent=2),
          "\n（受 LLM 接口限流影响，结果代表「端到端」而非服务本身上限）")
    _save({"load": summary})


# ---------------------------------------------------------------
# 4) 人工抽检计分
# ---------------------------------------------------------------
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
    p = sub.add_parser("agent"); p.add_argument("--repeat", type=int, default=1)
    sub.add_parser("retrieval")
    p = sub.add_parser("load"); p.add_argument("-c", type=int, default=5); p.add_argument("-n", type=int, default=20)
    p = sub.add_parser("score"); p.add_argument("path")
    a = ap.parse_args()

    if a.cmd == "agent":
        asyncio.run(eval_agent(a.repeat))
    elif a.cmd == "retrieval":
        eval_retrieval()
    elif a.cmd == "load":
        asyncio.run(eval_load(a.c, a.n))
    elif a.cmd == "score":
        score_labels(a.path)