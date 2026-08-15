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


def crawl(source):
    feed = feedparser.parse(source["url"])
    results = []

    for item in feed.entries:
        ok, ts = in_target_month(item)
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

#用 JSON 存的话,category 保留了列表结构,以后取出来可以直接 json.loads() 还原成 Python list,
# def crawl(source):
#     feed = feedparser.parse(source["url"])
#     results = []

#     # category 在yaml里可能是列表(如 Research/Industry),
#     # 用json.dumps转成字符串存进SQLite,取出来时json.loads还原成list
#     category = source["category"]
#     if isinstance(category, list):
#         category = json.dumps(category, ensure_ascii=False)
#     # 如果yaml里本来就是单个字符串,也统一包成list再转json,保证存储格式一致
#     else:
#         category = json.dumps([category], ensure_ascii=False)

#     for item in feed.entries:
#         ok, ts = in_target_month(item)
#         if not ok:
#             continue

#         title = clean_html(item.get("title", ""))
#         summary = clean_html(item.get("summary", ""))

#         if not title or not item.get("link"):
#             continue

#         results.append({
#             "title": title,
#             "summary": summary,
#             "url": item.get("link", ""),
#             "source": source["name"],
#             "language": source["language"],
#             "category": category,   # 已经是JSON字符串,如 '["Research", "Industry"]'
#             "published": item.get("published", ""),
#             "published_ts": ts,
#             "crawl_time": datetime.now().isoformat(),
#             "title_hash": title_hash(title),
#         })

#     return results

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


def run():
    config = load_sources()
    conn = init_db()
    all_news = []
    total_inserted, total_skipped = 0, 0

    for source in config["sources"]:
        print("crawl:", source["name"])
        news = crawl(source)
        all_news.extend(news)
        inserted, skipped = save_to_db(conn, news)
        total_inserted += inserted
        total_skipped += skipped

    save_path = BASE_DIR / "storage/raw/news.json"
    save_path.parent.mkdir(exist_ok=True, parents=True)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(all_news, f, ensure_ascii=False, indent=2)

    print(f"目标月份共 {len(all_news)} 条, 入库 {total_inserted}, 去重跳过 {total_skipped}")
    conn.close()


if __name__ == "__main__":
    run()