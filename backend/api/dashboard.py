from fastapi import APIRouter
from backend.services.news_service import dashboard_stats
from fastapi import APIRouter, Depends
from backend.deps import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("/stats")
def stats():
    return dashboard_stats()

@router.get("/api/dashboard/summary")
def summary(conn=Depends(get_db)):
    news = conn.execute(
        "SELECT COUNT(*) FROM news WHERE is_duplicate = 0 "
        "AND status IN ('analyzed','embedded','clustered','reported')"
    ).fetchone()[0]
    reports = conn.execute("SELECT COUNT(*) FROM daily_reports").fetchone()[0]
    events = conn.execute(
        "SELECT COUNT(*) FROM events WHERE last_published >= date('now','-30 days')"
    ).fetchone()[0]
    updated = conn.execute("SELECT MAX(updated_at) FROM daily_reports").fetchone()[0]
    return {"news": news, "reports": reports, "events_30d": events, "updated_at": updated}