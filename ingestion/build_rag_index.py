from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.rag_components import (
    build_vector_store,
    load_news_documents,
    save_vector_store,
    split_documents,
)
from storage.news_repository import (
    init_db,
    load_news_rows,
    map_url_to_news_id,
    rebuild_chunks,
    upsert_news_rows,
)


CSV_PATH = PROJECT_ROOT / "config" / "manual_news.csv"
DB_PATH = PROJECT_ROOT / "storage" / "news.db"
SCHEMA_PATH = PROJECT_ROOT / "storage" / "news_schema.sql"
VECTOR_PATH = PROJECT_ROOT / "storage" / "vector_store.pkl"


def main() -> None:
    init_db(DB_PATH, SCHEMA_PATH)
    rows = load_news_rows(CSV_PATH)
    upsert_news_rows(DB_PATH, rows)

    documents = load_news_documents(CSV_PATH)
    chunks = split_documents(documents)
    vector_store = build_vector_store(chunks)
    save_vector_store(vector_store, VECTOR_PATH)

    url_to_news_id = map_url_to_news_id(DB_PATH)
    db_chunks: list[tuple[int, int, str]] = []
    for chunk in chunks:
        url = chunk.metadata.get("url", "")
        news_id = url_to_news_id.get(url)
        if news_id is None:
            continue
        chunk_index = int(chunk.metadata.get("chunk_index", 0))
        db_chunks.append((news_id, chunk_index, chunk.page_content))
    rebuild_chunks(DB_PATH, db_chunks)

    print(f"Imported rows: {len(rows)}")
    print(f"Created chunks: {len(chunks)}")
    print(f"DB path: {DB_PATH}")
    print(f"Vector store path: {VECTOR_PATH}")


if __name__ == "__main__":
    main()
