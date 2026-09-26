"""
Active call state.

A call exists in exactly one place: the SignalingManager's in-memory room
registry, owned by the process serving /ws/signaling. This service is the read
side that turns those rooms into rows the dashboard can render, joining each
room to its interaction when the database is reachable so the row can name the
journey and department the call belongs to.

Two consequences, both accepted for a single-instance deployment and both
visible to callers:
- a process restart empties the list, because rooms only ever existed in memory
  (Signaling Module 3 keeps signaling state ephemeral on purpose);
- the list is only complete while the API and the signaling endpoint share a
  process, which they do because app.main:app serves both.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.interaction import Interaction
from app.routers import websocket_signaling

# Room states as reported to the dashboard. `waiting` means only one participant
# has joined; `ready` means both slots are filled and media setup can start.
STATE_WAITING = "waiting"
STATE_READY = "ready"


def _interaction_for(db: Optional[Session], call_id: str) -> Optional[Interaction]:
    """
    The interaction a room's call id points at, or None.

    The room key *is* the interaction UUID (see the signaling contract), but a
    lookup can still come up empty — the row may have been removed, or the id
    may not be a UUID at all — and the call is then reported without its
    database-derived fields rather than being dropped from the list.
    """
    if db is None:
        return None

    try:
        interaction_id = uuid.UUID(call_id)
    except (AttributeError, TypeError, ValueError):
        return None

    return (
        db.query(Interaction)
        .filter(Interaction.interaction_id == interaction_id)
        .first()
    )


def get_active_calls(db: Optional[Session] = None) -> List[Dict[str, Any]]:
    """
    Snapshot of every room currently held in memory, oldest call first.

    ``db`` is optional: without a session the signaling-derived fields are still
    returned and the database-derived ones are None, which is what makes the
    in-memory behaviour testable without PostgreSQL.
    """
    rooms = list(websocket_signaling.signaling_manager.rooms.items())

    calls: List[Dict[str, Any]] = []

    for call_id, room in rooms:
        interaction = _interaction_for(db, call_id)

        calls.append(
            {
                "call_id": call_id,
                "customer_peer_id": (
                    room.customer_peer.peer_id if room.customer_peer else None
                ),
                "employee_peer_id": (
                    room.employee_peer.peer_id if room.employee_peer else None
                ),
                "state": STATE_READY if room.is_ready() else STATE_WAITING,
                "started_at": room.created_at,
                "employee_id": interaction.employee_id if interaction else None,
                "journey_id": interaction.journey_id if interaction else None,
                "department_id": interaction.department_id if interaction else None,
                # A transfer is not a signaling concept: the REST transfer closes
                # this interaction with outcome "transferred" and opens a new one
                # in the target department, which becomes its own call. While that
                # hand-off has been issued but not yet re-joined, this row says so.
                "transfer_in_progress": bool(
                    interaction is not None and interaction.outcome == "transferred"
                ),
            }
        )

    # Aware datetimes throughout, so the fallback is aware too: comparing an
    # aware value with a naive one raises instead of sorting.
    calls.sort(
        key=lambda call: call["started_at"] or datetime.min.replace(tzinfo=timezone.utc)
    )

    return calls


def count_active_calls() -> int:
    """How many calls are live right now, for the analytics overview tile."""
    return len(websocket_signaling.signaling_manager.rooms)
