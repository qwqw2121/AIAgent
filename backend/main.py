from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.db import DB_PATH
from backend.api.news import router as news_router
from backend.api.dashboard import router as dashboard_router
from backend.api.sources import router as sources_router
from backend.api.events import router as events_router
from backend.api.reports import router as reports_router
from backend.api.rag import router as rag_router

app = FastAPI(title="AI News Agent API", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(news_router)
app.include_router(dashboard_router)
app.include_router(sources_router)
app.include_router(events_router)
app.include_router(reports_router)
app.include_router(rag_router)

@app.get("/")
def root():
    return {"name": "AI News Agent API", "status": "running", "db": str(DB_PATH), "db_exists": Path(DB_PATH).exists()}

@app.get("/api/health")
def health():
    return {"status": "ok", "db_exists": Path(DB_PATH).exists(), "db_path": str(DB_PATH)}
