"""
⑤ LLM 结构化分析

处理第一轮去重后剩下的、状态为 deduped（或上次分析失败 analyze_failed）的记录。
分析成功后写回数据库并置 status='analyzed'；失败则置 status='analyze_failed'。
支持按 published_ts 时间窗口过滤，供按天流水线调用：run(start_ts=..., end_ts=...)
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Any

from dotenv import load_dotenv

from agent.llm_client import chat_json
from agent.prompts import build_news_analysis_prompt
from storage.db import get_connection, update_fields

load_dotenv()


# ============================================================
# 配置
# ============================================================

MAX_WORKERS = 5
RATE_LIMIT_PER_SEC = 3
MAX_CONTENT_CHARS = 3000
REQUEST_TIMEOUT = 60
BATCH_COMMIT = 15

CATEGORIES = {
    "大模型发布", "融资并购", "政策监管", "研究论文",
    "产品发布", "行业观点", "其他",
}

KEYWORD_ALIASES = {
    "AI代理": "AI Agent",
    "AI智能体": "AI Agent",
    "智能体": "AI Agent",
    "具身": "具身智能",
}


# ============================================================
# 全局限流器
# ============================================================

class RateLimiter:
    """线程安全的全局请求间隔限流器。"""

    def __init__(self, per_sec: float):
        if per_sec <= 0:
            raise ValueError("per_sec 必须大于 0")

        self.interval = 1.0 / per_sec
        self.lock = Lock()
        self.next_time = 0.0

    def wait(self):
        # 锁内只分配时间槽，不在锁内 sleep。
        with self.lock:
            now = time.monotonic()
            scheduled_time = max(now, self.next_time)
            self.next_time = scheduled_time + self.interval

        delay = scheduled_time - time.monotonic()
        if delay > 0:
            time.sleep(delay)


_rate_limiter = RateLimiter(RATE_LIMIT_PER_SEC)


# ============================================================
# LLM 调用
# ============================================================

def analyze_news(title: str, content: str) -> dict:
    """调用 LLM 分析单条新闻，返回解析后的 JSON 字典。"""
    title = str(title or "").strip()
    content = str(content or "").strip()

    if len(content) < 10:
        content = title

    content = content[:MAX_CONTENT_CHARS]
    prompt = build_news_analysis_prompt(title, content)

    return chat_json(
        prompt=prompt,
        primary_env="LLM_ANALYSE",
        fallback_env="LLM_ANALYSE_FALLBACKS",
        temperature=0.3,
        timeout=REQUEST_TIMEOUT,
        before_request=_rate_limiter.wait,
    )


# ============================================================
# 结果校验与标准化
# ============================================================

def _normalize(result: dict[str, Any]) -> dict[str, Any]:
    """严格校验 LLM 输出，返回可直接写库的字段字典。"""
    if not isinstance(result, dict):
        raise ValueError("LLM 返回结果不是 JSON 对象")

    # summary
    summary = result.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary 为空或格式错误")
    summary = summary.strip()

    # category
    category = result.get("category")
    if not isinstance(category, str) or category not in CATEGORIES:
        raise ValueError(f"无效 category：{category!r}")

    # keywords
    keywords = result.get("keywords")
    if not isinstance(keywords, list):
        raise ValueError("keywords 必须是数组")

    normalized_keywords = []
    for item in keywords:
        if not isinstance(item, str) or not item.strip():
            continue

        keyword = item.strip()
        keyword = KEYWORD_ALIASES.get(keyword, keyword)

        if keyword not in normalized_keywords:
            normalized_keywords.append(keyword)

    if not 3 <= len(normalized_keywords) <= 5:
        raise ValueError(
            f"keywords 数量必须为 3-5 个，实际为 {len(normalized_keywords)} 个"
        )

    # importance：bool 是 int 的子类，因此需要显式排除。
    importance = result.get("importance")
    if isinstance(importance, bool) or not isinstance(importance, int):
        raise ValueError("importance 必须为整数")
    if not 1 <= importance <= 10:
        raise ValueError("importance 必须在 1-10 之间")

    return {
        "summary": summary,
        "llm_category": category,
        "keywords": json.dumps(normalized_keywords, ensure_ascii=False),
        "importance": importance,
        "status": "analyzed",
    }


# ============================================================
# 单条新闻分析
# ============================================================

def _analyze_one(row: dict, max_retry: int):
    """在线程中分析单条新闻，失败后按指数退避重试。"""
    content = row.get("content") or row.get("summary") or ""

    for attempt in range(max_retry + 1):
        try:
            result = analyze_news(row.get("title", ""), content)
            # 在工作线程中完成结果校验，避免无效结果进入主线程写库流程。
            normalized = _normalize(result)
            return row["id"], normalized, None

        except Exception as exc:
            print(
                f"  ⚠️ id={row['id']} 第{attempt + 1}次失败: {exc}",
                flush=True,
            )
            if attempt < max_retry:
                time.sleep(2 ** attempt)

    return row["id"], None, "达到最大重试次数"


# ============================================================
# 数据读取
# ============================================================

def fetch_pending(
    conn,
    max_items: int,
    per_source_cap: int,
    start_ts=None,
    end_ts=None,
) -> list[dict]:
    """
    读取待分析记录。
    每个来源最多取 per_source_cap 条最新记录，再按发布时间倒序取 max_items 条。
    时间窗口为 [start_ts, end_ts)。
    """
    if (start_ts is None) != (end_ts is None):
        raise ValueError("start_ts 和 end_ts 必须同时提供")
    if start_ts is not None and start_ts >= end_ts:
        raise ValueError("start_ts 必须小于 end_ts")
    if max_items <= 0 or per_source_cap <= 0:
        return []

    sql = """
        SELECT *
        FROM (
            SELECT
                n.*,
                ROW_NUMBER() OVER (
                    PARTITION BY source
                    ORDER BY published_ts DESC, id DESC
                ) AS rn
            FROM news n
            WHERE status IN ('deduped', 'analyze_failed')
              AND is_duplicate = 0
    """
    params = []

    if start_ts is not None:
        sql += " AND published_ts >= ? AND published_ts < ?"
        params.extend([start_ts, end_ts])

    sql += """
        )
        WHERE rn <= ?
        ORDER BY published_ts DESC, id DESC
        LIMIT ?
    """
    params.extend([per_source_cap, max_items])

    cursor = conn.execute(sql, params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# ============================================================
# 主流程
# ============================================================

def run(
    max_items: int = 150,
    per_source_cap: int = 30,
    max_retry: int = 2,
    start_ts=None,
    end_ts=None,
) -> dict:
    """
    并发运行 LLM 结构化分析。

    Args:
        max_items: 本次最多处理条数
        per_source_cap: 每个来源最多处理条数
        max_retry: 单条失败后的最大重试次数（不含首次请求）
        start_ts: 可选，发布时间窗口起点（包含）
        end_ts: 可选，发布时间窗口终点（不包含）
    """
    if (start_ts is None) != (end_ts is None):
        raise ValueError("start_ts 和 end_ts 必须同时提供")
    if start_ts is not None and start_ts >= end_ts:
        raise ValueError("start_ts 必须小于 end_ts")
    if max_retry < 0:
        raise ValueError("max_retry 不能小于 0")

    conn = get_connection()
    try:
        rows = fetch_pending(
            conn,
            max_items=max_items,
            per_source_cap=per_source_cap,
            start_ts=start_ts,
            end_ts=end_ts,
        )

        if not rows:
            print("✅ 没有待分析或可重试的新闻")
            return {"total": 0, "success": 0, "failed": 0}

        total = len(rows)
        print(f"📊 待 LLM 分析/重试: {total} 条")

        success_count = 0
        failed_count = 0
        pending_commits = 0

        try:
            # 工作线程只调用 LLM 和校验结果；SQLite 读写全部留在主线程。
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_row = {
                    executor.submit(_analyze_one, row, max_retry): row
                    for row in rows
                }

                for index, future in enumerate(as_completed(future_to_row), 1):
                    row = future_to_row[future]
                    news_id = row["id"]

                    try:
                        _, normalized, error = future.result()
                    except Exception as exc:
                        normalized = None
                        error = str(exc)

                    write_ok = False

                    if normalized is not None:
                        try:
                            result = update_fields(
                                conn, news_id, normalized, commit=False
                            )
                            write_ok = result is not False
                        except Exception as exc:
                            error = f"写库失败: {exc}"

                    if not write_ok:
                        try:
                            update_fields(
                                conn,
                                news_id,
                                {"status": "analyze_failed"},
                                commit=False,
                            )
                        except Exception as exc:
                            # 如果数据库连接/事务本身已不可用，不能假装状态更新成功。
                            print(
                                f"  ❌ id={news_id} 更新失败状态也失败: {exc}",
                                flush=True,
                            )

                        failed_count += 1
                        print(
                            f"  ❌ id={news_id} 分析失败: {error or '未知错误'}",
                            flush=True,
                        )
                    else:
                        success_count += 1

                    pending_commits += 1
                    if pending_commits >= BATCH_COMMIT:
                        conn.commit()
                        pending_commits = 0

                    print(
                        f"[{index}/{total}] id={news_id} "
                        f"{'✅' if write_ok else '❌'}",
                        flush=True,
                    )

        finally:
            # 提交已完成的结果；若连接异常，交由外层 finally 关闭连接。
            conn.commit()

        print(
            f"\n📊 本次完成：成功 {success_count}，失败 {failed_count}，共 {total}"
        )
        return {
            "total": total,
            "success": success_count,
            "failed": failed_count,
        }

    finally:
        conn.close()


# ============================================================
# 统计
# ============================================================

def get_analysis_stats() -> dict:
    """查看各状态的数据量统计。"""
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
