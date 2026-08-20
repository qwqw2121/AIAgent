from fastapi import APIRouter
from backend.services.event_service import list_events

router = APIRouter(prefix="/api/events", tags=["events"])

@router.get("")
def events():
    return list_events()
