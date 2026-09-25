from dataclasses import dataclass
from typing import Any, Optional

from app.signaling.exceptions import RoomFull
from app.signaling.models import PeerRole


@dataclass
class Peer:
    """
    Represents one participant connected to a signaling room.

    The websocket object is intentionally typed as Any so this module
    stays independent of FastAPI/WebSocket implementation details.
    """

    peer_id: str
    role: PeerRole
    websocket: Any


class Room:
    """
    In-memory signaling room.

    A room can contain:
    - exactly one customer
    - exactly one employee

    Room state is transient and must not be persisted to PostgreSQL.
    """

    def __init__(self, call_id: str):
        self.room_id = f"call:{call_id}"
        self.customer_peer: Optional[Peer] = None
        self.employee_peer: Optional[Peer] = None

    def add_peer(self, peer: Peer) -> None:
        """
        Add a peer to the appropriate role slot.

        Raises:
            RoomFull: if that role is already occupied.
        """
        if peer.role == PeerRole.CUSTOMER:
            if self.customer_peer is not None:
                raise RoomFull("Room already has a customer.")
            self.customer_peer = peer

        elif peer.role == PeerRole.EMPLOYEE:
            if self.employee_peer is not None:
                raise RoomFull("Room already has an employee.")
            self.employee_peer = peer

    def remove_peer(self, peer_id: str) -> None:
        """
        Remove a peer by peer_id.

        Safe to call even when the peer does not exist.
        """
        if self.customer_peer and self.customer_peer.peer_id == peer_id:
            self.customer_peer = None
            return

        if self.employee_peer and self.employee_peer.peer_id == peer_id:
            self.employee_peer = None

    def get_other_peer(self, peer_id: str) -> Optional[Peer]:
        """
        Return the peer on the opposite side of the room.

        Returns None if:
        - the requested peer is not in the room
        - the opposite peer has not joined yet
        """
        if self.customer_peer and self.customer_peer.peer_id == peer_id:
            return self.employee_peer

        if self.employee_peer and self.employee_peer.peer_id == peer_id:
            return self.customer_peer

        return None

    def is_ready(self) -> bool:
        """Return True when both customer and employee are connected."""
        return (
            self.customer_peer is not None
            and self.employee_peer is not None
        )