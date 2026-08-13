import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("GLM_API_KEY", "test-key")

import agent.news_analyzer as news_analyzer


def _connect(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_run_retries_failed_analysis(tmp_path, monkeypatch):
    db_path = tmp_path / "news.db"
    conn = _connect(db_path)
    conn.execute(
        """
        CREATE TABLE news (
            id INTEGER PRIMARY KEY,
            url TEXT,
            title TEXT,
            content TEXT,
            summary TEXT,
            source TEXT,
            published TEXT,
            published_ts TEXT,
            crawl_time TEXT,
            status TEXT,
            is_duplicate INTEGER DEFAULT 0,
            llm_category TEXT,
            keywords TEXT,
            importance INTEGER
        )
        """
    )
    conn.execute(
        "INSERT INTO news (title, content, status, is_duplicate) VALUES (?, ?, ?, ?)",
        ("Failed article", "Body text", "analyze_failed", 0),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(news_analyzer, "DB_PATH", db_path)
    monkeypatch.setattr(news_analyzer, "get_connection", lambda: _connect(db_path))
    monkeypatch.setattr(
        news_analyzer,
        "analyze_news",
        lambda title, content: {
            "summary": "已重新分析并生成摘要",
            "category": "政策监管",
            "keywords": ["政策", "监管"],
            "importance": 7,
        },
    )

    news_analyzer.run(sleep_sec=0, max_retry=1)

    final = _connect(db_path).execute(
        "SELECT status, summary, llm_category, importance FROM news WHERE title = ?",
        ("Failed article",),
    ).fetchone()
    assert final is not None
    assert final["status"] == "analyzed"
    assert final["summary"] == "已重新分析并生成摘要"
    assert final["llm_category"] == "政策监管"
    assert final["importance"] == 7
