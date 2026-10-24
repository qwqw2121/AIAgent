from fastapi import APIRouter, Depends
from backend.deps import get_db
from backend.services.news_service import dashboard_stats

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("/stats")
def stats(conn=Depends(get_db)):
    data = dashboard_stats()          # 假设返回 dict（含 total_news 等）
    data["total_reports"] = conn.execute(
        "SELECT COUNT(*) FROM daily_reports").fetchone()[0]
    data["events_30d"] = conn.execute(
        "SELECT COUNT(*) FROM events "
        "WHERE news_count >= 2 AND last_published >= date('now','-30 days')"
    ).fetchone()[0]
    return data