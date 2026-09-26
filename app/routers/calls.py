"""
Active call endpoints.

Reads the in-memory signaling room registry, so the Active Calls dashboard page
has something real to render while Signaling Modules 3-4 keep that state
deliberately unsaved.
"""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.call import ActiveCallOut
from app.services import calls_service

router = APIRouter(prefix="/api/v1/calls", tags=["calls"])


@router.get("/active", response_model=List[ActiveCallOut])
def list_active_calls(db: Session = Depends(get_db)):
    """
    Every call in progress, oldest first.

    A call appears as soon as the first participant's join creates its room, and
    disappears when the last participant leaves — hangup, disconnect or a dropped
    socket all remove it. Rooms live in this process' memory only, so a restart
    mid-call leaves this list empty; that is the accepted trade for not persisting
    signaling state, not a bug.
    """
    return calls_service.get_active_calls(db)
