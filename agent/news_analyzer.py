"""
⑤ LLM结构化分析
处理第一轮去重后剩下的、状态为 deduped（或上次分析失败 analyze_failed）的记录，
分析完写回数据库并置 status='analyzed'；失败则置 status='analyze_failed'，下次自动重试。

支持按 published_ts 时间窗口过滤，供按天流水线调用：
    run(start_ts=..., end_ts=...)
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from textwrap import dedent
from threading import Lock
from typing import Any, Dict, Optional
from agent.llm_client import chat_json
from dotenv import load_dotenv

from storage.db import get_connection, update_fields

load_dotenv()

# ============================================================
# 配置
# ============================================================

MAX_WORKERS = 5               # 并发线程数，LLM API 通常有并发限制，宜保守
RATE_LIMIT_PER_SEC = 3        # 全局每秒最多发起的请求数，请参考服务商限速文档
MAX_CONTENT_CHARS = 3000      # 送入模型的正文最大字符数
REQUEST_TIMEOUT = 60          # 单次请求超时（秒）
BATCH_COMMIT = 15             # 每处理多少条提交一次数据库

CATEGORIES = {"大模型发布", "融资并购", "政策监管", "研究论文", "产品发布", "行业观点", "其他"}


# ============================================================
# 全局限流器：保证所有线程合计不超过 RATE_LIMIT_PER_SEC 次/秒
# ============================================================

class RateLimiter:
    def __init__(self, per_sec: float):
        self.interval = 1.0 / per_sec
        self.lock = Lock()
        self.next_time = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            delay = self.next_time - now
            if delay > 0:
                time.sleep(delay)
            self.next_time = max(now, self.next_time) + self.interval


_rate_limiter = RateLimiter(RATE_LIMIT_PER_SEC)


# ============================================================
# LLM 调用
# ============================================================

def analyze_news(title: str, content: str) -> dict:
    """调用 LLM 分析单条新闻，返回解析后的 JSON 字典"""
    if not content or len(content.strip()) < 10:
        content = title
    content = content[:MAX_CONTENT_CHARS]

    prompt = dedent(f"""\
        你是AI资讯分析专家。
        分析下面新闻：
        标题:
        {title}
        正文:
        {content}

        输出JSON，格式如下:
        {{
          "summary": "概括性摘要",
          "category": "分类",
          "keywords": ["关键词1", "关键词2", "关键词3"],
          "importance": 整数
        }}

        要求：
        - summary控制在80-120字，突出新闻的核心事实和影响
        - category从以下选择: 大模型发布|融资并购|政策监管|研究论文|产品发布|行业观点|其他
        - keywords 3-5个
        - importance为1-10的整数，10代表行业级重大事件(如头部公司发布新一代模型)，1代表边角小消息，请根据实际重要程度打分
        - summary必须是你对新闻事件的概括性转述，不能是原文的同义词替换或句式微调
        - 严禁逐句改写原文表述，要用你自己的语言重新组织信息
        """)

    return chat_json(
    prompt=prompt,
    primary_env="LLM_ANALYSE",
    fallback_env="LLM_ANALYSE_FALLBACKS",
    temperature=0.3,
    timeout=REQUEST_TIMEOUT,
    before_request=_rate_limiter.wait,
)


def _normalize(result: Dict[str, Any]) -> Dict[str, Any]:
    """校验并清洗 LLM 输出，返回可直接写库的字段字典"""
    summary = result.get("summary", "")
    summary = summary.strip() if isinstance(summary, str) else ""

    category = result.get("category", "其他")
    if category not in CATEGORIES:
        category = "其他"

    keywords = result.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []
    keywords = [str(k).strip() for k in keywords if str(k).strip()][:5]

    try:
        importance = max(1, min(10, int(result.get("importance", 1))))
    except (TypeError, ValueError):
        importance = 1

    return {
        "summary": summary,
        "llm_category": category,
        "keywords": json.dumps(keywords, ensure_ascii=False),
        "importance": importance,
        "status": "analyzed",
    }


def _analyze_one(row: dict, max_retry: int):
    """分析单条记录（在工作线程中运行），失败按指数退避重试"""
    content = row.get("content") or row.get("summary") or ""
    result: Optional[dict] = None

    for attempt in range(max_retry + 1):
        try:
            result = analyze_news(row["title"], content)
            break
        except Exception as e:
            print(f"  ⚠️ id={row['id']} 第{attempt + 1}次失败: {e}", flush=True)
            if attempt < max_retry:
                time.sleep(2 ** attempt) #指数退避（Exponential Backoff）。

    return row["id"], result


# ============================================================
# 数据读取
# ============================================================

def fetch_pending(conn, max_items: int, per_source_cap: int,
                  start_ts=None, end_ts=None):
    """
    取待分析记录：每个来源最多取 per_source_cap 条最新的，
    再按发布时间倒序总共取 max_items 条，避免单一来源占满额度。

    传入 start_ts/end_ts 时，只取 published_ts 落在 [start_ts, end_ts) 的记录。
    """
    sql = """
        SELECT * FROM (
            SELECT n.*,
                   ROW_NUMBER() OVER (PARTITION BY source ORDER BY published_ts DESC) AS rn
            FROM news n
            WHERE status IN ('deduped', 'analyze_failed')
              AND is_duplicate = 0
    """
    params = []

    if start_ts is not None:
        sql += " AND published_ts >= ? AND published_ts < ?"
        params += [start_ts, end_ts]

    sql += """
        )
        WHERE rn <= ?
        ORDER BY published_ts DESC
        LIMIT ?
    """
    params += [per_source_cap, max_items]

    cur = conn.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ============================================================
# 主流程
# ============================================================

def run(max_items: int = 150, per_source_cap: int = 30, max_retry: int = 2,
        start_ts=None, end_ts=None) -> dict:
    """
    并发运行 LLM 结构化分析（批量提交版）。

    Args:
        max_items: 本次最多处理条数
        per_source_cap: 每个来源最多处理条数
        max_retry: 单条失败后的最大重试次数
        start_ts: 可选，只处理 published_ts >= start_ts 的记录
        end_ts:   可选，只处理 published_ts < end_ts 的记录
                  start_ts 和 end_ts 需同时提供
    """
    if (start_ts is None) != (end_ts is None):
        raise ValueError("start_ts 和 end_ts 必须同时提供")
    if start_ts is not None and start_ts >= end_ts:
        raise ValueError("start_ts 必须小于 end_ts")

    conn = get_connection()
    try:
        rows = fetch_pending(
            conn, max_items, per_source_cap,
            start_ts=start_ts, end_ts=end_ts,
        )
        if not rows:
            print("✅ 没有待分析或可重试的新闻")
            return {"total": 0, "success": 0, "failed": 0}

        total = len(rows)
        print(f"📊 待LLM分析/重试: {total} 条")
        ok = fail = pending = 0

        try:
            # 工作线程只调用 LLM；所有数据库读写都在主线程，避免 sqlite 线程问题
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                futures = {ex.submit(_analyze_one, r, max_retry): r for r in rows}
                for i, fut in enumerate(as_completed(futures), 1):
                    news_id = futures[fut]["id"]
                    try:
                        _, result = fut.result()
                    except Exception as e:
                        result = None
                        print(f"  ❌ id={news_id} 异常: {e}", flush=True)

                    success = False
                    if result is not None:
                        try:
                            success = update_fields(
                                conn, news_id, _normalize(result), commit=False
                            ) is not False
                        except Exception as e:
                            print(f"  ❌ id={news_id} 写库失败: {e}", flush=True)

                    if success:
                        ok += 1
                    else:
                        update_fields(conn, news_id, {"status": "analyze_failed"}, commit=False)
                        fail += 1

                    pending += 1
                    if pending >= BATCH_COMMIT:
                        conn.commit()
                        pending = 0

                    print(f"[{i}/{total}] id={news_id} {'✅' if success else '❌'}", flush=True)
        finally:
            # 正常结束、异常或 Ctrl+C 中断时，都把已完成的结果提交
            conn.commit()

        print(f"\n📊 本次完成：成功 {ok}，失败 {fail}，共 {total}")
        return {"total": total, "success": ok, "failed": fail}
    finally:
        conn.close()


def get_analysis_stats() -> dict:
    """查看各状态的数据量统计"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT status, COUNT(*) AS count
            FROM news
            WHERE is_duplicate = 0
            GROUP BY status
        """)
        stats = {row[0]: row[1] for row in cursor.fetchall()}
    finally:
        conn.close()

    print("\n📊 数据库统计:")
    print(f"  待采集 (raw): {stats.get('raw', 0)}")
    print(f"  已提取 (extracted): {stats.get('extracted', 0)}")
    print(f"  已去重待分析 (deduped): {stats.get('deduped', 0)}")
    print(f"  已分析 (analyzed): {stats.get('analyzed', 0)}")
    print(f"  分析失败 (analyze_failed): {stats.get('analyze_failed', 0)}")
    print(f"  总计: {sum(stats.values())}")
    return stats


if __name__ == "__main__":
    get_analysis_stats()
    run(max_items=150, per_source_cap=30, max_retry=3)