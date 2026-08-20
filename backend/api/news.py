from fastapi import APIRouter, HTTPException, Query
from backend.services.news_service import list_news, get_news, dashboard_stats, list_sources

router = APIRouter(prefix="/api/news", tags=["news"])

@router.get("")
def api_list_news(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    category: str | None = None,
    source: str | None = None,
    q: str | None = None,
    importance: int | None = Query(None, ge=1, le=5),
):
    return list_news(limit, offset, category, source, q, importance)

@router.get("/{news_id}")
def api_get_news(news_id: int):
    item = get_news(news_id)
    if item is None:
        raise HTTPException(status_code=404, detail="News not found")
    return item
