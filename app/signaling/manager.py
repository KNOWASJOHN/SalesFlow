"""
Signaling Module 3: Signaling Manager.

The manager owns the registry of every active call and is the single place
where a signaling message is routed from one peer to the other.

Design constraints (from the WebRTC signaling build plan):
- State is ephemeral, in-memory only. Nothing here is ever persisted to
  PostgreSQL; a process restart legitimately loses every room.
- Routing is strictly intra-room: a message is only ever delivered to the
  opposite peer of the *same* call_id, never to another room.
- Methods are ``async`` because they await websocket writes; the manager
  itself stays free of FastAPI/Starlette imports and is unit-testable with
  plain fake websocket objects.
"""

from typing import Any

from app.signaling.exceptions import RoomNotFound
from app.signaling.models import PeerRole, SignalingMessage
from app.signaling.room import Peer, Room
from app.signaling.protocol import serialize_message


class SignalingManager:
    """Registry and routing layer for active WebRTC signaling rooms."""

    def __init__(self):
        # call_id -> Room
        self.rooms: dict[str, Room] = {}

    async def register_peer(
        self,
        call_id: str,
        peer_id: str,
        role: PeerRole,
        websocket: Any,
    ) -> Room:
        """
        Add a peer to the room for ``call_id``, creating the room on first join.

        The customer and employee slots are filled independently, so this can be
        called in either order (employee first is perfectly valid).

        Raises:
            RoomFull: if that role's slot in this room is already taken. The
                pre-existing room is left untouched so the connected peer is
                never evicted by a rejected newcomer.
        """
        room = self.rooms.get(call_id)

        if room is None:
            room = Room(call_id)
            self.rooms[call_id] = room

        peer = Peer(
            peer_id=peer_id,
            role=role,
            websocket=websocket,
        )

        room.add_peer(peer)

        return room

    async def send_to_peer(
        self,
        call_id: str,
        sender: str,
        message: SignalingMessage,
    ) -> None:
        """
        Forward ``message`` to the peer on the opposite side of ``sender``.

        ``sender`` is the authenticated peer_id and is used purely for routing;
        stamping the outgoing envelope's ``sender`` field is the WebSocket
        endpoint's job (Module 4), so it is deliberately not done here.

        A message sent before the opposite peer has joined is a no-op rather
        than an error — the endpoint decides whether to queue or nudge the
        caller with a ``ready``/``call_state`` message.

        Raises:
            RoomNotFound: if no room exists for ``call_id``.
        """
        room = self.rooms.get(call_id)

        if room is None:
            raise RoomNotFound(
                f"Room not found for call_id: {call_id}"
            )

        target_peer = room.get_other_peer(sender)

        if target_peer is None:
            return

        await target_peer.websocket.send_text(
            serialize_message(message)
        )

    async def remove_peer(
        self,
        call_id: str,
        peer_id: str,
    ) -> None:
        """
        Remove a peer during disconnect cleanup.

        Idempotent by contract: calling it twice, for an already-removed peer,
        or for a room that does not exist all succeed silently. Once the last
        peer leaves, the room itself is discarded.
        """
        room = self.rooms.get(call_id)

        if room is None:
            return

        room.remove_peer(peer_id)

        if room.customer_peer is None and room.employee_peer is None:
            self.rooms.pop(call_id, None)

    async def notify_peer_left(self, call_id: str, peer_id: str) -> None:
        """
        Tell the *remaining* peer that ``peer_id`` has dropped out of the call.

        Called before the disconnecting peer is removed from the room, because
        once it is gone ``get_other_peer`` can no longer resolve the survivor
        from the leaver's identity.

        This is deliberately separate from :meth:`remove_peer`, which stays
        idempotent and silent: a caller that tears a whole room down via
        :meth:`close_room` has already told the survivor the call ended, and
        must not follow it with a second notice.

        Safe to call for an unknown ``call_id`` or a peer that is not in the
        room — both are silent no-ops.
        """
        room = self.rooms.get(call_id)

        if room is None:
            return

        remaining_peer = room.get_other_peer(peer_id)

        if remaining_peer is None:
            return

        message = SignalingMessage(
            type="call_state",
            call_id=call_id,
            payload={"state": "peer_left"},
        )

        await remaining_peer.websocket.send_text(
            serialize_message(message)
        )

    async def close_room(self, call_id: str) -> None:
        """
        Tear the room down, notifying any peer still connected.

        The remaining peer receives a ``call_state`` message with
        ``{"state": "ended"}`` so its client can update the UI, after which
        the room is removed from the registry. Safe to call for an unknown
        ``call_id``.
        """
        room = self.rooms.get(call_id)

        if room is None:
            return

        remaining_peer = room.customer_peer or room.employee_peer

        if remaining_peer is not None:
            message = SignalingMessage(
                type="call_state",
                call_id=call_id,
                payload={"state": "ended"},
            )

            await remaining_peer.websocket.send_text(
                serialize_message(message)
            )

        self.rooms.pop(call_id, None)
