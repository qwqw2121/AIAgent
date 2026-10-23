"""
ingestion/backfill_crawler.py

历史日期回补爬虫：RSS 只保留最近几天，更早的日期靠这里按日期查询。
接口与 ingestion.rss_crawler.run 保持一致：run(target_date=...) 返回同结构的 stats，
数据写入同一张 news 表（url UNIQUE，重复抓取不会产生重复行）。

当前支持：
  - arXiv API（按 submittedDate 范围查询）
  - Hacker News（Algolia search_by_date，按时间范围 + 关键词 + 分数过滤）
"""
import calendar
import time
from datetime import date, datetime, timezone

import feedparser
import requests

from storage.db import get_connection
from pipeline.utils import day_bounds_ts
from ingestion.rss_crawler import HEADERS, clean_html, title_hash, save_to_db

TIMEOUT = (5, 20)
REQUEST_INTERVAL = 3  # 秒；arXiv 要求请求间隔 >= 3 秒

# ---------- arXiv ----------
ARXIV_SOURCE = "arXiv (backfill)"
ARXIV_CATEGORIES = ["cs.AI", "cs.CL", "cs.LG"]
ARXIV_MAX_PER_DAY = 40

# ---------- Hacker News ----------
HN_SOURCE = "Hacker News (backfill)"
HN_KEYWORDS = [
    "LLM", "OpenAI", "Anthropic", "GPT", "Claude", "Gemini",
    "machine learning", "neural network", "AI agent",
]
HN_MIN_POINTS = 30
HN_MAX_PER_DAY = 30


def _get(url, params=None, retries=2):
    last = None
    for i in range(retries):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last = e
            time.sleep(REQUEST_INTERVAL)
    raise last


def _make_news(title, summary, url, source, language, category, ts):
    iso_time = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
    return {
        "title": title,
        "summary": summary,
        "url": url,
        "source": source,
        "language": language,
        "category": category,
        "published": iso_time,
        "published_ts": ts,
        "crawl_time": datetime.now().isoformat(),
        "title_hash": title_hash(title),
    }


def fetch_arxiv(day_start_ts, day_end_ts):
    fmt = "%Y%m%d%H%M"
    s = datetime.fromtimestamp(day_start_ts, tz=timezone.utc).strftime(fmt)
    e = datetime.fromtimestamp(day_end_ts - 60, tz=timezone.utc).strftime(fmt)
    cats = " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES)

    resp = _get(
        "https://export.arxiv.org/api/query",
        params={
            "search_query": f"({cats}) AND submittedDate:[{s} TO {e}]",
            "start": 0,
            "max_results": ARXIV_MAX_PER_DAY,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        },
    )
    feed = feedparser.parse(resp.content)

    news = []
    for entry in feed.entries:
        parsed = entry.get("published_parsed")
        title = clean_html(entry.get("title", ""))
        link = entry.get("link")
        if not parsed or not title or not link:
            continue
        news.append(_make_news(
            title=title,
            summary=clean_html(entry.get("summary", "")),
            url=link,
            source=ARXIV_SOURCE,
            language="en",
            category="Research",
            ts=calendar.timegm(parsed),
        ))
    return news


def fetch_hn(day_start_ts, day_end_ts):
    hits_by_id = {}
    for kw in HN_KEYWORDS:
        resp = _get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={
                "query": kw,
                "tags": "story",
                "numericFilters": (
                    f"created_at_i>={day_start_ts},"
                    f"created_at_i<{day_end_ts},"
                    f"points>={HN_MIN_POINTS}"
                ),
                "hitsPerPage": 50,
            },
        )
        for hit in resp.json().get("hits", []):
            hits_by_id.setdefault(hit["objectID"], hit)
        time.sleep(1)

    hits = sorted(
        hits_by_id.values(), key=lambda h: h.get("points") or 0, reverse=True
    )[:HN_MAX_PER_DAY]

    news = []
    for hit in hits:
        title = clean_html(hit.get("title") or "")
        if not title:
            continue
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
        news.append(_make_news(
            title=title,
            summary="",
            url=url,
            source=HN_SOURCE,
            language="en",
            category="Community,Aggregator",
            ts=hit["created_at_i"],
        ))
    return news


FETCHERS = [
    (ARXIV_SOURCE, fetch_arxiv),
    (HN_SOURCE, fetch_hn),
]


def run(target_date: date) -> dict:
    s, e = day_bounds_ts(target_date.isoformat())
    conn = get_connection()

    total_fetched = total_inserted = total_skipped = 0
    per_source, failed_sources = [], []

    print(f"[backfill] 目标: {target_date}, 共 {len(FETCHERS)} 个回补源", flush=True)

    try:
        for name, fetcher in FETCHERS:
            try:
                news = fetcher(s, e)
            except Exception as ex:
                print(f"[backfill] ❌ {name}: {type(ex).__name__}: {ex}", flush=True)
                failed_sources.append(name)
                continue

            inserted, skipped = save_to_db(conn, news)
            total_fetched += len(news)
            total_inserted += inserted
            total_skipped += skipped
            per_source.append({
                "source": name,
                "fetched": len(news),
                "inserted": inserted,
                "skipped": skipped,
            })
            print(f"[backfill] ✅ {name}: 命中 {len(news)}, 入库 {inserted}, 跳过 {skipped}",
                  flush=True)
            time.sleep(REQUEST_INTERVAL)
    finally:
        conn.close()

    return {
        "target_year": target_date.year,
        "target_month": target_date.month,
        "target_date": str(target_date),
        "total_fetched": total_fetched,
        "total_inserted": total_inserted,
        "total_skipped": total_skipped,
        "failed_sources": failed_sources,
        "per_source": per_source,
    }


if __name__ == "__main__":
    from datetime import timedelta
    print(run(date.today() - timedelta(days=20)))