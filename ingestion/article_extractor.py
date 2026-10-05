"""
ingestion/article_extractor.py

URL → 网页正文 → 更新 content / extract_status / status

流程:
  raw ──成功──────────────▶ extracted
  raw ──跳过(arXiv等)─────▶ extracted (用 RSS 摘要, extract_status=skipped_domain)
  raw ──失败──▶ extract_failed ──再失败(达到 MAX_ATTEMPTS)──▶ extracted (降级用 RSS 摘要)

要点:
1. 统一用 requests 下载(带超时), trafilatura / readability 只负责解析, 每篇只请求一次
2. 按域名限速, 同一域名两次请求至少间隔 MIN_INTERVAL 秒
3. arXiv / HF Papers 等无需抓网页的源直接跳过
4. 重试用完仍失败的, 降级放行, 不再卡死在 extract_failed
5. 数据库统一走 storage.db.get_connection
"""

import importlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
import trafilatura

from storage.db import get_connection

# ============================================================
# 配置
# ============================================================
MIN_CONTENT_LEN = 80        # 正文短于此长度视为提取失败
FETCH_TIMEOUT = 10          # 读取超时(秒)
CONNECT_TIMEOUT = 5         # 连接超时(秒)
MAX_WORKERS = 5             # 并发线程数
MIN_INTERVAL = 1.0          # 同一域名两次请求的最小间隔(秒)
MAX_ATTEMPTS = 2            # 失败项最多尝试次数, 用完后降级放行
DEFAULT_LIMIT = 500         # 单次运行最多处理多少条, 剩下的留给下一次

# 这些站点无需抓网页, RSS 摘要已够用(且常 403)
SKIP_FETCH_DOMAINS = ("arxiv.org", "huggingface.co", "dl.acm.org")

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    )
}


# ============================================================
# 数据库字段
# ============================================================
def ensure_columns(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(news)")}
    if "extract_status" not in cols:
        conn.execute("ALTER TABLE news ADD COLUMN extract_status TEXT")
    if "extract_attempts" not in cols:
        conn.execute("ALTER TABLE news ADD COLUMN extract_attempts INTEGER DEFAULT 0")
    conn.commit()


# ============================================================
# 按域名限速
# ============================================================
_domain_next = {}
_domain_lock = threading.Lock()


def _throttle(url):
    host = urlparse(url).netloc
    with _domain_lock:
        now = time.monotonic()
        slot = max(now, _domain_next.get(host, 0.0))
        _domain_next[host] = slot + MIN_INTERVAL
        wait = slot - now
    if wait > 0:
        time.sleep(wait)


def should_skip(url):
    host = urlparse(url).netloc.lower()
    return any(d in host for d in SKIP_FETCH_DOMAINS)


# ============================================================
# 下载与解析
# ============================================================
def fetch_html(url):
    resp = requests.get(url, headers=UA, timeout=(CONNECT_TIMEOUT, FETCH_TIMEOUT))
    resp.raise_for_status()
    return resp.text


def _trafilatura_text(html):
    try:
        return trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
    except Exception as e:
        print(f"trafilatura error: {type(e).__name__}: {e}", flush=True)
        return None


def _readability_text(html):
    """trafilatura 失败/内容太短时的兜底, 复用已下载的 html"""
    try:
        mod = importlib.import_module("readability")
        Document = getattr(mod, "Document", None)
        if Document is None:
            Document = importlib.import_module("readability.readability").Document
        raw = Document(html).summary()
        text = re.sub(r"<[^>]+>", " ", raw)
        return re.sub(r"\s+", " ", text).strip()
    except Exception as e:
        print(f"readability error: {type(e).__name__}: {e}", flush=True)
        return None


def extract_content(url):
    """返回 (content or None, extract_status)"""
    try:
        html = fetch_html(url)
    except Exception as e:
        print(f"fetch error: {url} {type(e).__name__}", flush=True)
        return None, "failed"

    text = _trafilatura_text(html)
    if text and len(text) >= MIN_CONTENT_LEN:
        return text, "ok_trafilatura"

    text = _readability_text(html)
    if text and len(text) >= MIN_CONTENT_LEN:
        return text, "ok_readability"

    return None, "failed"


# ============================================================
# 写库
# ============================================================
def update_content(conn, news_id, content, extract_status):
    """
    主 status 驱动流水线:
      提取成功 / 跳过域名      → extracted
      失败但还有重试次数       → extract_failed
      失败且重试用完           → extracted (降级使用 RSS 摘要)
    extract_status 只作为调试信息。
    """
    if content or extract_status == "skipped_domain":
        main_status = "extracted"
    else:
        prev = conn.execute(
            "SELECT COALESCE(extract_attempts, 0) FROM news WHERE id=?", (news_id,)
        ).fetchone()
        attempts = (prev[0] if prev else 0) + 1
        if attempts >= MAX_ATTEMPTS:
            main_status = "extracted"
            extract_status = "fallback_summary"
        else:
            main_status = "extract_failed"

    conn.execute(
        """UPDATE news
           SET content=?, extract_status=?, status=?,
               extract_attempts = COALESCE(extract_attempts, 0) + 1
           WHERE id=?""",
        (content, extract_status, main_status, news_id),
    )
    conn.commit()


# ============================================================
# 单条工作单元(在线程中运行, 不碰数据库)
# ============================================================
def _extract_one(news_id, url):
    if should_skip(url):
        return news_id, None, "skipped_domain"
    try:
        _throttle(url)
        content, status = extract_content(url)
    except Exception as e:
        print(f"extract error id={news_id}: {type(e).__name__}: {e}", flush=True)
        content, status = None, "failed"
    return news_id, content, status


# ============================================================
# 主流程
# ============================================================
def run(start_ts=None, end_ts=None, limit=DEFAULT_LIMIT):
    conn = get_connection()
    try:
        ensure_columns(conn)

        sql = """SELECT id, url FROM news
                 WHERE content IS NULL
                   AND (status = 'raw'
                        OR (status = 'extract_failed'
                            AND COALESCE(extract_attempts, 0) < ?))"""
        params = [MAX_ATTEMPTS]
        if start_ts is not None:
            sql += " AND published_ts >= ? AND published_ts < ?"
            params += [start_ts, end_ts]
        sql += " ORDER BY published_ts DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        total = len(rows)
        ok = failed = skipped = 0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(_extract_one, r[0], r[1]): r[0] for r in rows}
            for n, fut in enumerate(as_completed(futures), 1):
                try:
                    news_id, content, status = fut.result()
                except Exception as e:
                    print(f"worker error: {type(e).__name__}: {e}", flush=True)
                    failed += 1
                    continue

                update_content(conn, news_id, content, status)   # 主线程写库

                if content:
                    ok += 1
                elif status == "skipped_domain":
                    skipped += 1
                else:
                    failed += 1
                print(f"[{n}/{total}] id={news_id} status={status}", flush=True)

        return {"total": total, "success": ok, "failed": failed, "skipped": skipped}
    finally:
        conn.close()


if __name__ == "__main__":
    print(run())