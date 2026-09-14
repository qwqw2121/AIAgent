-- storage/schema.sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS news (
    id SERIAL PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    title_hash TEXT,
    source TEXT,
    language TEXT,
    category TEXT,
    published TEXT,
    published_ts BIGINT,
    crawl_time TEXT,
    content TEXT,
    summary TEXT,
    llm_category TEXT,
    keywords TEXT,
    importance INTEGER,
    status TEXT DEFAULT 'raw',
    is_duplicate INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_status ON news(status);
CREATE INDEX IF NOT EXISTS idx_published_ts ON news(published_ts);