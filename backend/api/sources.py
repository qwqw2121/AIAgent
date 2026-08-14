from fastapi import APIRouter
from backend.services.news_service import list_sources

router = APIRouter(prefix="/api/sources", tags=["sources"])

@router.get("")
def sources():
    return {"data": list_sources()}
