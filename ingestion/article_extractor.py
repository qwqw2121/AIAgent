#URL变正文，提取 RSS正文内容
#url → 网页正文 → 更新content字段

"""
URL变正文,提取RSS正文内容
url → 网页正文 → 更新content字段 + status字段

相比原版加了:
1. status字段区分 "还没抓" / "抓成功" / "抓失败",失败的不会被无限重试
2. 限速,避免同一时间集中请求把自己IP打进小黑屋
3. 内容长度校验,过短的判定为无效,不当成功处理
4. trafilatura失败时用readability兜底一次
 正文提取 → status='extracted
"""

import time
import sqlite3
import importlib
import trafilatura
from pathlib import Path

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "storage/news.db"  # ✅ 相对于文件位置，稳定

MIN_CONTENT_LEN = 80       # 正文短于这个长度,视为提取失败(反爬页/空页面常见现象)
SLEEP_SEC = 1.0            # 每条之间的间隔,防止被目标网站封IP
FETCH_TIMEOUT = 10         # trafilatura.fetch_url底层用的是urllib,可通过config传超时


MAX_WORKERS = 5             # 同时并发的线程数，建议先从 5-10 试起
RATE_LIMIT_PER_SEC = 3       # 每秒最多发起几个请求，防止把自己IP打进小黑屋
_rate_limiter = Semaphore(RATE_LIMIT_PER_SEC)

def ensure_columns(conn):
    """确保 extract_status 字段存在,不存在就自动加上(方便你在老库上直接跑,不用手动改表)"""
    cursor = conn.execute("PRAGMA table_info(news)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if "extract_status" not in existing_cols:
        conn.execute("ALTER TABLE news ADD COLUMN extract_status TEXT")
        conn.commit()


def extract_with_trafilatura(url):
    try:
        html = trafilatura.fetch_url(url)
        if not html:
            return None
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
        return text
    except Exception as e:
        print("trafilatura error:", url, e)
        return None


def extract_with_readability(url):
    """trafilatura失败/内容太短时的兜底方案"""
    try:
        readability_module = importlib.import_module("readability")
        Document = getattr(readability_module, "Document", None)
        if Document is None:
            Document = importlib.import_module("readability.readability").Document

        import requests
        resp = requests.get(url, timeout=FETCH_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"
        })
        resp.raise_for_status()
        doc = Document(resp.text)
        import re
        raw = doc.summary()
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
        return text
    except Exception as e:
        print("readability error:", url, e)
        return None


def extract_content(url):
    """返回 (content or None, status)"""
    text = extract_with_trafilatura(url)
    if text and len(text) >= MIN_CONTENT_LEN:
        return text, "ok_trafilatura"

    text = extract_with_readability(url)
    if text and len(text) >= MIN_CONTENT_LEN:
        return text, "ok_readability"

    return None, "failed"


def update_content(conn, news_id, content, extract_status):
    """
    更新新闻内容，同时更新主 status 和 extract_status
    
    主 status 字段驱动整个pipeline流转:
    - content 提取成功 → status = 'extracted' (等待LLM分析)
    - content 提取失败 → status = 'extract_failed' (不会继续处理)
    
    extract_status 只是细粒度的调试信息:
    - 记录使用了哪种提取方法: ok_trafilatura / ok_readability / failed
    """
    # 根据是否提取到内容决定主状态
    main_status = "extracted" if content else "extract_failed"
    
    conn.execute(
        "UPDATE news SET content=?, extract_status=?, status=? WHERE id=?",
        (content, extract_status, main_status, news_id),
    )
    conn.commit()

def _extract_one(news_id, url):
    """单条提取的工作单元，供线程池调用"""
    with _rate_limiter:
        content, status = extract_content(url)
        time.sleep(1.0 / RATE_LIMIT_PER_SEC)  # 简单的令牌桶节流
    return news_id, content, status

def run():
    conn = sqlite3.connect(DB_PATH)
    ensure_columns(conn)
    rows = conn.execute(
        "SELECT id, url FROM news WHERE content IS NULL AND status = 'raw'"
    ).fetchall()

    ok, failed = 0, 0

    # #串行
    # for i, (news_id, url) in enumerate(rows, 1):
    #     content, status = extract_content(url)
    #     update_content(conn, news_id, content, status)
    #     if content:
    #         ok += 1
    #     else:
    #         failed += 1
    #     time.sleep(SLEEP_SEC)
    
    #改成线程池并发，同时保留限速（避免把目标网站的反爬机制打进小黑屋）：
    # ⚠️ sqlite3 连接不是线程安全的，不能让多个线程共用同一个 conn 写入
    # 所以写入操作统一放在主线程，工作线程只负责网络请求+抓正文
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_extract_one, news_id, url): news_id
            for news_id, url in rows
        }
        for i, future in enumerate(as_completed(futures), 1):
            news_id, content, status = future.result()
            update_content(conn, news_id, content, status)   # 主线程写库
            if content:
                ok += 1
            else:
                failed += 1
            print(f"[{i}/{len(rows)}] id={news_id} status={status}")

    conn.close()
    return {"total": len(rows), "success": ok, "failed": failed}   # ⭐ 新增返回值


if __name__ == "__main__":
    run()