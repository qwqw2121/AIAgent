from fastapi import APIRouter, HTTPException, Query
from backend.services.news_service import list_news, get_news
from storage.db import fetch_important_recent

router = APIRouter(prefix="/api/news", tags=["news"])

@router.get("")
def api_list_news(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    category: str | None = None,
    source: str | None = None,
    q: str | None = None,
    importance: int | None = Query(None, ge=1, le=10),
):
    return list_news(limit, offset, category, source, q, importance)

# 必须放在 /{news_id} 之前，否则 "important" 会被当成 news_id
@router.get("/important")
def api_important_news(
    limit: int = Query(8, ge=1, le=200),
    min_importance: int = Query(7, ge=1, le=10),
    hours: int = Query(24, ge=1, le=720),
):
    return fetch_important_recent(limit, min_importance, hours)

@router.get("/{news_id}")
def api_get_news(news_id: int):
    item = get_news(news_id)
    if item is None:
        raise HTTPException(status_code=404, detail="News not found")
    return item