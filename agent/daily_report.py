'''SQLite
 ↓
获取当天重要新闻
 ↓
交给 LLM
 ↓
生成结构化日报
 ↓
保存数据库'''

# agent/daily_report.py

import os
import json
import sqlite3
from datetime import datetime, date
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# =========================================================
# 配置
# =========================================================


# 设置路径
# DB_PATH = Path("storage/news.db") #绝对路径
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "storage/news.db"

# 使用 OpenAI 或 OpenAI-compatible API
API_KEY = os.getenv(
    "LLM_API_KEY"
)

BASE_URL = os.getenv(
    "LLM_BASE_URL"
)

MODEL_NAME = os.getenv(
    "LLM_ANALYSE"
)

client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL
)

# =========================================================
# 数据库
# =========================================================

def get_db():
    return sqlite3.connect(DB_PATH)


def init_daily_report_table():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_date TEXT UNIQUE NOT NULL,
        overview TEXT,
        report_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


# =========================================================
# 获取当天新闻
# =========================================================

from email.utils import parsedate_to_datetime

from datetime import datetime, date, timedelta, timezone

REPORT_STATUSES = ("analyzed", "embedded", "embed_failed", "clustered", "reported")
MAX_NEWS_FOR_LLM = 50


def _day_range_ts(report_date: str):
    d = date.fromisoformat(report_date)
    start = datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


from pipeline.utils import day_bounds_ts, SQL_TZ

READY = ("clustered", "reported")      # 已走完全部处理的新闻
MAX_NEWS_FOR_LLM = 50


def find_pending_dates(limit=10):
    """有 clustered(还没进日报)新闻的日期,最新的优先"""
    conn = get_db()
    rows = conn.execute(f"""
        SELECT date(published_ts,'unixepoch','{SQL_TZ}') AS d, COUNT(*)
        FROM news
        WHERE status = 'clustered' AND is_duplicate = 0
          AND summary IS NOT NULL AND importance IS NOT NULL
          AND published_ts IS NOT NULL
        GROUP BY d
        ORDER BY d DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_news_by_date(report_date):
    start_ts, end_ts = day_bounds_ts(report_date)
    ph = ",".join("?" * len(READY))
    conn = get_db()
    rows = conn.execute(f"""
        SELECT id, title, source, published, summary, llm_category,
               keywords, importance, url, status
        FROM news
        WHERE is_duplicate = 0
          AND status IN ({ph})
          AND importance IS NOT NULL
          AND published_ts >= ? AND published_ts < ?
        ORDER BY importance DESC, published_ts DESC
        LIMIT ?
    """, (*READY, start_ts, end_ts, MAX_NEWS_FOR_LLM)).fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "source": r[2], "published": r[3],
             "summary": r[4], "category": r[5], "keywords": r[6],
             "importance": r[7], "url": r[8], "status": r[9]} for r in rows]


# =========================================================
# 构造 LLM Prompt
# =========================================================

def build_prompt(news_list):
    """
    把新闻整理成 LLM 可以理解的文本
    """

    news_text = []

    for news in news_list:

        news_text.append(
            f"""
新闻ID：{news["id"]}
标题：{news["title"]}
来源：{news["source"]}
发布时间：{news["published"]}
分类：{news["category"]}
关键词：{news["keywords"]}
重要性：{news["importance"]}
摘要：{news["summary"]}
"""
        )

    news_text = "\n".join(news_text)

    prompt = f"""
你是一名 AI 科技资讯编辑。

下面是今天收集到的 AI 新闻。

你的任务是生成一份“今日 AI 资讯日报”。

要求：

1. 先给出今天整体发生了什么的 overview。
2. 从新闻中筛选最值得关注的 5~10 个事件。
3. 相同事件的新闻需要合并，不要重复总结。
4. 每个事件给出：
   - title
   - summary
   - why_it_matters
   - news_ids
5. news_ids 必须使用提供给你的真实新闻ID。
6. 不允许自己创造新闻ID。
7. 不要创造不存在的信息。
8. 总结应该简洁，适合直接展示在网页上。
9. 输出必须是合法 JSON。
10. 不要使用 Markdown。

输出格式：

{{
    "overview": "今天AI领域整体发生了什么",
    "events": [
        {{
            "title": "事件标题",
            "summary": "事件简要总结",
            "why_it_matters": "为什么值得关注",
            "news_ids": [1, 2]
        }}
    ]
}}

今天的新闻：

{news_text}
"""

    return prompt


# =========================================================
# 调用 LLM
# =========================================================

def generate_daily_report(news_list):

    if not news_list:
        return {
            "overview": "今天暂无重要 AI 新闻。",
            "events": []
        }

    prompt = build_prompt(news_list)

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": "你是一名专业的AI科技资讯编辑，只输出合法JSON。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.2
    )

    content = response.choices[0].message.content

    # 防止模型返回 ```json
    content = content.strip()

    if content.startswith("```"):
        content = content.replace("```json", "")
        content = content.replace("```", "")
        content = content.strip()

    return json.loads(content)


# =========================================================
# 根据新闻ID补充原始新闻信息
# =========================================================

def attach_news_info(report, valid_ids):
    """
    LLM只负责总结。
    新闻标题、来源、URL等从数据库获取。

    这样可以避免LLM编造URL。
    """

    conn = get_db()
    for event in report.get("events", []):
        ids = []
        for i in event.get("news_ids", []):
            try:
                i = int(i)
            except (TypeError, ValueError):
                continue
            if i in valid_ids:
                ids.append(i)
        event["news_ids"] = ids

        if not ids:
            event["news"] = []
            continue
        ph = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT id, title, source, published, url FROM news WHERE id IN ({ph})", ids
        ).fetchall()
        event["news"] = [
            {"id": r[0], "title": r[1], "source": r[2], "published": r[3], "url": r[4]}
            for r in rows
        ]
    conn.close()
    return report

def mark_reported(report):
    ids = {i for e in report.get("events", []) for i in e.get("news_ids", [])}
    if not ids:
        return
    conn = get_db()
    ph = ",".join("?" * len(ids))
    conn.execute(f"UPDATE news SET status='reported' WHERE id IN ({ph})", list(ids))
    conn.commit()
    conn.close()
# =========================================================
# 保存日报
# =========================================================

def save_daily_report(report_date, report):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO daily_reports (
            report_date,
            overview,
            report_json
        )
        VALUES (?, ?, ?)
        ON CONFLICT(report_date)
        DO UPDATE SET
            overview = excluded.overview,
            report_json = excluded.report_json
    """, (
        report_date,
        report.get("overview", ""),
        json.dumps(
            report,
            ensure_ascii=False
        )
    ))

    conn.commit()
    conn.close()


# =========================================================
# 生成完整日报
# =========================================================

def create_daily_report(report_date=None):

    if report_date is None:
        report_date = date.today().isoformat()

    print(f"开始生成 {report_date} 的日报...")

    init_daily_report_table()

    news_list = get_news_by_date(report_date)
    if not news_list:
        return None
    report = generate_daily_report(news_list)
    report = attach_news_info(report, {n["id"] for n in news_list})
    save_daily_report(report_date, report)
    mark_reported(news_list)
    return report

# =========================================================
# 测试
# =========================================================

if __name__ == "__main__":

    report = create_daily_report()

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        )
    )