import csv
import sqlite3
from pathlib import Path


def get_db_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path, schema_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_db_connection(db_path) as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))


def load_news_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def upsert_news_rows(db_path: Path, rows: list[dict[str, str]]) -> None:
    sql = """
    INSERT INTO news (title, source, published_at, summary, category, original_url)
    VALUES (:title, :source, :published_at, :summary, :category, :url)
    ON CONFLICT(original_url) DO UPDATE SET
        title = excluded.title,
        source = excluded.source,
        published_at = excluded.published_at,
        summary = excluded.summary,
        category = excluded.category
    """
    with get_db_connection(db_path) as conn:
        conn.executemany(sql, rows)
        conn.commit()


def rebuild_chunks(db_path: Path, chunks: list[tuple[int, int, str]]) -> None:
    with get_db_connection(db_path) as conn:
        conn.execute("DELETE FROM news_chunks")
        conn.executemany(
            "INSERT INTO news_chunks(news_id, chunk_index, chunk_text) VALUES (?, ?, ?)",
            chunks,
        )
        conn.commit()


def map_url_to_news_id(db_path: Path) -> dict[str, int]:
    with get_db_connection(db_path) as conn:
        rows = conn.execute("SELECT id, original_url FROM news").fetchall()
    return {row["original_url"]: row["id"] for row in rows}
