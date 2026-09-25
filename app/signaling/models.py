import uuid
from enum import Enum
from typing import Optional, Any, Dict
from datetime import datetime
from pydantic import BaseModel, Field


class MessageType(str, Enum):
    JOIN = "join"
    READY = "ready"
    OFFER = "offer"
    ANSWER = "answer"
    ICE_CANDIDATE = "ice_candidate"
    CALL_STATE = "call_state"
    HANGUP = "hangup"
    ERROR = "error"


class PeerRole(str, Enum):
    CUSTOMER = "customer"
    EMPLOYEE = "employee"


class SignalingMessage(BaseModel):
    """
    The one message envelope every signaling participant (backend, employee
    web client, Flutter client) sends and receives. This shape is the
    contract — do not add/rename fields without updating all three sides.
    """

    type: MessageType
    call_id: str
    interaction_id: Optional[uuid.UUID] = None
    sender: Optional[str] = None  # server overwrites this on the way out; never trust client-supplied sender
    target: Optional[str] = None  # optional explicit recipient peer_id; usually inferred (the "other" peer in the room)
    payload: Dict[str, Any] = Field(default_factory=dict)  # SDP / ICE data, shape varies by `type` — not validated here
    timestamp: Optional[datetime] = None


class JoinPayload(BaseModel):
    """
    The payload of the first frame a client sends: the role it claims to be.

    The claim is *not* trusted — the endpoint compares it against the role in
    the authenticated token and refuses the join on any mismatch.
    """

    role: PeerRole
