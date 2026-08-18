# 在基础采集器基础上改造,加入:时间过滤、URL唯一去重、标题hash去重、HTML清洗:
# 采集后的数据清洗后直接入库

import feedparser  # 注意你原代码写的是 feedparserd,是笔误
import yaml
import json
import re
import hashlib
import sqlite3
import calendar
from pathlib import Path
from datetime import datetime
from datetime import datetime, timezone

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "storage/news.db"

TARGET_YEAR = 2026
TARGET_MONTH = 8


def init_db():
    conn = sqlite3.connect(DB_PATH)
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
    """清洗:去HTML标签、压缩多余空白"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def title_hash(title):
    """标题归一化(小写+去空白)后取hash,用于精确去重"""
    norm = re.sub(r"\s+", "", title.lower())
    return hashlib.md5(norm.encode("utf-8")).hexdigest()


def in_target_month(entry):
    """时间过滤:只保留目标年月"""
    parsed = entry.get("published_parsed")
    if not parsed:
        return False, None
    ts = calendar.timegm(parsed)  # UTC时间戳,比字符串比较更可靠
    # dt = datetime.utcfromtimestamp(ts)
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return (dt.year == TARGET_YEAR and dt.month == TARGET_MONTH), ts


def load_sources():
    path = BASE_DIR / "sources/rss_sources.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def normalize_category(category):
    if isinstance(category, list):
        return ",".join(category)
    return category or ""

def in_target_month(entry, target_year: int, target_month: int):
    parsed = entry.get("published_parsed")
    if not parsed:
        return False, None
    ts = calendar.timegm(parsed)
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return (dt.year == target_year and dt.month == target_month), ts


def crawl(source, target_year: int, target_month: int):
    feed = feedparser.parse(source["url"])
    results = []
    for item in feed.entries:
        ok, ts = in_target_month(item, target_year, target_month)
# def crawl(source):
#     feed = feedparser.parse(source["url"])
#     results = []

#     for item in feed.entries:
#         ok, ts = in_target_month(item)
        if not ok:
            continue  # 跳过非目标月份
        # 生成 ISO 8601 格式
        parsed = item.get("published_parsed")
        if parsed:
            # ✅ 使用 fromtimestamp 替代 utcfromtimestamp
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            iso_time = dt.isoformat(timespec='seconds').replace('+00:00', '+00:00')
        else:
            iso_time = ""
            
        title = clean_html(item.get("title", ""))
        summary = clean_html(item.get("summary", ""))

        if not title or not item.get("link"):
            continue  # 清洗:标题/链接缺失的脏数据直接丢弃

        results.append({
            "title": title,
            "summary": summary,
            "url": item.get("link", ""),
            "source": source["name"],
            "language": source["language"],
            "category": normalize_category(source.get("category")),
            "published": iso_time,
            "published_ts": ts,
            "crawl_time": datetime.now().isoformat(),
            "title_hash": title_hash(title),
        })

    return results
'''title_hash 字段用于"标题精确去重"，但 save_to_db() 里实际生效的去重只有 url 的唯一约束
（靠 IntegrityError 捕获），title_hash 字段目前只是存了值，并没有真正用来判断重复。
如果目标是"同一标题不同 URL 也算重复"（比如转载文章链接不同但标题相同），需要在插入前额外查一次：'''
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
                news["summary"]
            ))
            inserted += 1
        except sqlite3.IntegrityError:
            # url 唯一约束冲突 -> 已存在,直接去重跳过
            skipped += 1
    conn.commit()
    return inserted, skipped

def run(target_year: int = None, target_month: int = None) -> dict:
    now = datetime.now(timezone.utc)
    target_year = target_year or now.year
    target_month = target_month or now.month

    config = load_sources()
    conn = init_db()
    total_fetched, total_inserted, total_skipped = 0, 0, 0
    per_source_stats = []

    for source in config["sources"]:
        news = crawl(source, target_year, target_month)
        inserted, skipped = save_to_db(conn, news)
        total_fetched += len(news)
        total_inserted += inserted
        total_skipped += skipped
        per_source_stats.append({
            "source": source["name"],
            "fetched": len(news),
            "inserted": inserted,
            "skipped": skipped,
        })

    conn.close()

    return {
        "target_year": target_year,
        "target_month": target_month,
        "total_fetched": total_fetched,
        "total_inserted": total_inserted,
        "total_skipped": total_skipped,
        "per_source": per_source_stats,
    }
# def run():
#     config = load_sources()
#     conn = init_db()
#     all_news = []
#     total_inserted, total_skipped = 0, 0

#     for source in config["sources"]:
#         print("crawl:", source["name"])
#         news = crawl(source)
#         all_news.extend(news)
#         inserted, skipped = save_to_db(conn, news)
#         total_inserted += inserted
#         total_skipped += skipped

#     save_path = BASE_DIR / "storage/raw/news.json"
#     save_path.parent.mkdir(exist_ok=True, parents=True)
#     with open(save_path, "w", encoding="utf-8") as f:
#         json.dump(all_news, f, ensure_ascii=False, indent=2)

#     print(f"目标月份共 {len(all_news)} 条, 入库 {total_inserted}, 去重跳过 {total_skipped}")
#     conn.close()


if __name__ == "__main__":
    run()