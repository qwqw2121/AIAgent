# ingestion/rss_crawler.py
import calendar
import hashlib
import os
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import feedparser
import requests
import yaml

DB_PATH = os.getenv("NEWS_DB_PATH", Path(__file__).parent.parent / "storage/news.db")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ai-news-agent/1.0)"}
CONNECT_TIMEOUT = 5     # 连接超时(秒)
READ_TIMEOUT = 15       # 读取超时(秒)
FETCH_WORKERS = 8       # 并发拉取 RSS 的线程数(只做网络请求)


def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        title_hash TEXT,
        source TEXT,
        language TEXT,
        category TEXT,
        published TEXT,
        published_ts INTEGER,
        crawl_time TEXT,
        content TEXT,
        summary TEXT,
        llm_category TEXT,
        keywords TEXT,
        importance INTEGER,
        status TEXT DEFAULT 'raw',
        is_duplicate INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON news(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_published_ts ON news(published_ts)")
    conn.commit()
    return conn


def clean_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_hash(title):
    norm = re.sub(r"\s+", "", title.lower())
    return hashlib.md5(norm.encode("utf-8")).hexdigest()


def load_sources():
    path = os.getenv("SOURCES_PATH", Path(__file__).parent.parent / "sources/rss_sources.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_category(category):
    if isinstance(category, list):
        return ",".join(category)
    return category or ""


def match_target(entry, target_year, target_month, target_date=None):
    """时间过滤:指定 target_date 时按天过滤,否则按年月过滤(UTC)"""
    parsed = entry.get("published_parsed")
    if not parsed:
        return False, None
    ts = calendar.timegm(parsed)
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if target_date is not None:
        return dt.date() == target_date, ts
    return (dt.year == target_year and dt.month == target_month), ts


def fetch_feed(source):
    """带超时地拉取并解析一个 RSS 源(可能抛异常,由调用方处理)"""
    resp = requests.get(
        source["url"], headers=HEADERS, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
    )
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def parse_entries(source, feed, target_year, target_month, target_date=None):
    results = []
    for item in feed.entries:
        ok, ts = match_target(item, target_year, target_month, target_date)
        if not ok:
            continue

        title = clean_html(item.get("title", ""))
        summary = clean_html(item.get("summary", ""))
        if not title or not item.get("link"):
            continue

        iso_time = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")

        results.append({
            "title": title,
            "summary": summary,
            "url": item["link"],
            "source": source["name"],
            "language": source["language"],
            "category": normalize_category(source.get("category")),
            "published": iso_time,
            "published_ts": ts,
            "crawl_time": datetime.now().isoformat(),
            "title_hash": title_hash(title),
        })
    return results


def save_to_db(conn, news_list):
    inserted, skipped = 0, 0
    for news in news_list:
        try:
            conn.execute("""
                INSERT INTO news
                (url, title, title_hash, source, language, category,
                 published, published_ts, crawl_time, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                news["url"], news["title"], news["title_hash"],
                news["source"], news["language"], news["category"],
                news["published"], news["published_ts"], news["crawl_time"],
                news["summary"],
            ))
            inserted += 1
        except sqlite3.IntegrityError:
            skipped += 1
    conn.commit()
    return inserted, skipped


def run(target_year: int = None, target_month: int = None, target_date: date = None) -> dict:
    now = datetime.now(timezone.utc)
    if target_date is not None:
        target_year, target_month = target_date.year, target_date.month
    target_year = target_year or now.year
    target_month = target_month or now.month

    config = load_sources()
    sources = config["sources"]
    conn = init_db()

    total_fetched = total_inserted = total_skipped = 0
    per_source_stats, failed_sources = [], []

    print(f"[crawl] 共 {len(sources)} 个源, 目标: "
          f"{target_date or f'{target_year}-{target_month:02d}'}", flush=True)

    # 并发拉取网络(不碰数据库),完成一个处理一个
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        future_map = {pool.submit(fetch_feed, s): s for s in sources}

        for fut in as_completed(future_map):
            source = future_map[fut]
            try:
                feed = fut.result()
            except Exception as e:
                print(f"[crawl] ❌ {source['name']}: {type(e).__name__}: {e}", flush=True)
                failed_sources.append(source["name"])
                continue

            news = parse_entries(source, feed, target_year, target_month, target_date)
            inserted, skipped = save_to_db(conn, news)   # 主线程写库
            total_fetched += len(news)
            total_inserted += inserted
            total_skipped += skipped
            per_source_stats.append({
                "source": source["name"],
                "fetched": len(news),
                "inserted": inserted,
                "skipped": skipped,
            })
            print(f"[crawl] ✅ {source['name']}: 命中 {len(news)}, 入库 {inserted}, 跳过 {skipped}",
                  flush=True)

    conn.close()

    return {
        "target_year": target_year,
        "target_month": target_month,
        "target_date": str(target_date) if target_date else None,
        "total_fetched": total_fetched,
        "total_inserted": total_inserted,
        "total_skipped": total_skipped,
        "failed_sources": failed_sources,
        "per_source": per_source_stats,
    }


if __name__ == "__main__":
    run()