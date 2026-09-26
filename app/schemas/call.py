import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ActiveCallOut(BaseModel):
    """
    One live signaling room.

    ``employee_id``, ``journey_id`` and ``department_id`` are resolved from the
    interaction the call is about and are None when that lookup finds nothing.
    There is no stored call table behind any of this: the list is a snapshot of
    process memory, so it is empty after a restart.
    """

    call_id: str
    customer_peer_id: Optional[str] = None
    employee_peer_id: Optional[str] = None
    employee_id: Optional[uuid.UUID] = None
    journey_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None
    state: str
    started_at: Optional[datetime] = None
    transfer_in_progress: bool = False
