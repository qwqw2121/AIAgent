# backend/api/trends.py
# 趋势页接口。SQL 都在 storage/db.py 的 fetch_trends 里。
# 注意：这里不再定义 /news/important，它统一由 backend/api/news.py 提供。

from fastapi import APIRouter, Query
from storage.db import fetch_trends

router = APIRouter(prefix="/api", tags=["trends"])


@router.get("/trends")
def get_trends(days: int = Query(30, ge=1, le=90)):
    return fetch_trends(days)