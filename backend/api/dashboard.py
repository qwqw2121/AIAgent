from fastapi import APIRouter
from backend.services.news_service import dashboard_stats

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("/stats")
def stats():
    return dashboard_stats()
