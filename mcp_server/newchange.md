P0：可能直接影响功能

1. get_daily_report 返回 sqlite3.Row，且内容会被截断

main.py 里用 report_row["report_json"] 访问，说明 fetch_report_by_date 返回的是 sqlite3.Row。Row 不是 dict，MCP 在序列化或做输出校验时很可能失败（请实测确认）。应 dict(result)。
更隐蔽的是：report_json 可能很长，但 agent_node 对所有送入 LLM 的 ToolMessage 都做 _shrink（3000 字符），包括本轮刚返回的。你的 prompt 说"日报类回答可以更完整"，实际模型只看到被截断的前 3000 字。
修法：在 MCP 里把日报压缩成"overview + 每个事件的标题与一句话摘要"，或给日报类工具放宽 _shrink 阈值。
'''
@mcp.tool()
def get_daily_report(report_date: str) -> dict:
    """获取指定日期(YYYY-MM-DD)的每日新闻简报；没有则 content 为 null"""
    try:
        datetime.strptime(report_date, "%Y-%m-%d")
    except ValueError:
        return {"error": "日期格式应为 YYYY-MM-DD"}
    conn = get_connection()
    try:
        row = fetch_report_by_date(conn, report_date)
        if not row:
            return {"content": None}
        report = json.loads(row["report_json"])
        return {
            "date": row["report_date"],
            "overview": row["overview"],
            "events": [
                {"title": e.get("title"), "summary": _snippet(e.get("summary"), 150),
                 "news_ids": e.get("news_ids", [])}
                for e in report.get("events", [])[:12]
            ],
        }
    finally:
        conn.close()
'''

2. limit / top_k 为 None 时 min() 抛 TypeError

模型偶尔会显式传 null。用 limit = max(1, min(limit or 8, MAX_TOP_K))。同理 keyword: str = None 应写成 Optional[str] = None，让 schema 明确可空。

P1：检索质量

3. 没有相似度阈值，永远返回 Top-K

向量检索只会返回"最近的 K 个"，不保证"相关"。冷门问题（比如库里没有的话题）也会返回 5 条不相关新闻，模型会硬凑答案，这是幻觉的主要来源。你 prompt 里"检索结果为空就如实说明"在当前实现下几乎永远触发不了。

4. 没有时间过滤，也无法回答"今天的 AI 新闻"

语义检索不理解"今天"。today 虽注入了 prompt，但工具没有日期参数。需要在 metadata 存数值型时间戳（例如 published_ts），工具增加 days: int | None 并做 metadata filter。注意 Chroma 等库的范围过滤要求数值，字符串日期不能做 $gte。

5. 同一新闻多 chunk 重复、结果缺乏多样性

按 news_id 去重；或使用 MMR（max_marginal_relevance_search）。

6. 缺少 category 取值约束

search_news 的 category 是自由字符串，模型会瞎猜分类名（"AI"”人工智能"”LLM"）导致查不到。应在 docstring 里列出合法值，或用 Literal[...] 让 schema 带 enum。

7. 返回里没有序号，但 prompt 要求 [序号] 引用

模型得自己编号。可在结果里加 "ref": i+1，引用与结果严格对应，减少错标。

P2：并发与稳定性

8. 同步工具会阻塞 MCP 进程的事件循环

FastMCP 对同步函数是直接调用的（请以你所用 SDK 版本为准）。embedding 如果是远程 API 或大模型推理，会卡住整个 stdio 进程，所有并发请求排队。改成 async def + asyncio.to_thread。

9. stdio 单子进程是吞吐瓶颈，且崩溃后 graph.py 里没有重连。规模上去后改为 streamable-http transport 独立部署。

改进后的语义检索参考实现
python
MIN_SCORE = 0.35   # 需用标注集调；分数含义取决于向量库与距离度量

@mcp.tool()
async def search_news_semantic(query: str, top_k: int = 5, days: int | None = None) -> list[dict]:
    """按主题/话题/问题做语义检索（如“强化学习相关新闻”）。
    days 可选，仅返回最近 N 天的新闻。同一问题只需调用一次。"""
    top_k = max(1, min(top_k or 5, MAX_TOP_K))
    flt = None
    if days:
        cutoff = int(time.time()) - days * 86400
        flt = {"published_ts": {"$gte": cutoff}}      # 过滤语法随向量库而异

    def _search():
        return vectorstore.similarity_search_with_relevance_scores(
            query, k=top_k * 3, filter=flt)           # 多取，便于去重+阈值后仍够数

    pairs = await asyncio.to_thread(_search)

    seen, results = set(), []
    for d, score in pairs:
        if score < MIN_SCORE:
            continue
        m = d.metadata or {}
        key = m.get("news_id") or m.get("url")
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "ref": len(results) + 1,
            "title": m.get("title", "未知标题"),
            "content": _snippet(d.page_content),
            "source": m.get("source", "未知来源"),
            "url": m.get("url") or m.get("link"),
            "published": m.get("published_at") or m.get("date"),
            "score": round(score, 3),
        })
        if len(results) >= top_k:
            break
    return results            # 空列表 → 模型据此如实回答“没有相关新闻”