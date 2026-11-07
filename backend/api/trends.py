from fastapi import APIRouter, Query
from storage.db import fetch_trends, fetch_tech_news

router = APIRouter(prefix="/api", tags=["trends"])


@router.get("/trends")
def get_trends(days: int = Query(30, ge=1, le=90)):
    return fetch_trends(days)


@router.get("/trends/tech-news")
def get_tech_news(
    name: str = Query(..., min_length=1),
    days: int = Query(30, ge=1, le=90),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return fetch_tech_news(name, days, limit, offset)