r"""
Signaling Module 3 (Signaling Manager) — unit tests.

These tests are pure in-memory: no database, no network, no browser, no
Flutter. `FakeWebSocket` stands in for the live socket so we can assert
exactly which peer a message was delivered to.

Run from the backend project root:
    .\.venv\Scripts\python.exe -m pytest tests/test_signaling_manager.py -q
"""

import json

import pytest

from app.signaling.exceptions import RoomFull, RoomNotFound
from app.signaling.manager import SignalingManager
from app.signaling.models import MessageType, PeerRole, SignalingMessage
from app.signaling.protocol import validate_message

# pytest-asyncio is installed in strict mode, so async tests opt in explicitly.
pytestmark = pytest.mark.asyncio

CALL_ID = "call-001"
CUSTOMER_ID = "customer-001"
EMPLOYEE_ID = "employee-001"


class FakeWebSocket:
    """Minimal stand-in for a Starlette WebSocket (only what the manager uses)."""

    def __init__(self, name: str = "socket"):
        self.name = name
        self.sent: list[str] = []
        self.closed = False

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True


def make_message(
    message_type: MessageType = MessageType.OFFER,
    call_id: str = CALL_ID,
    payload: dict | None = None,
) -> SignalingMessage:
    return SignalingMessage(
        type=message_type,
        call_id=call_id,
        payload={"sdp": "v=0"} if payload is None else payload,
    )


async def register_pair(
    manager: SignalingManager,
    call_id: str = CALL_ID,
    customer_id: str = CUSTOMER_ID,
    employee_id: str = EMPLOYEE_ID,
) -> tuple[FakeWebSocket, FakeWebSocket]:
    """Register a customer + employee on the same call, in that order."""
    customer_ws = FakeWebSocket("customer")
    employee_ws = FakeWebSocket("employee")

    await manager.register_peer(call_id, customer_id, PeerRole.CUSTOMER, customer_ws)
    await manager.register_peer(call_id, employee_id, PeerRole.EMPLOYEE, employee_ws)

    return customer_ws, employee_ws


# ---------------------------------------------------------------------------
# 1-4: registry + peer registration
# ---------------------------------------------------------------------------


async def test_register_peer_creates_room_and_returns_it():
    manager = SignalingManager()
    ws = FakeWebSocket("customer")

    room = await manager.register_peer(CALL_ID, CUSTOMER_ID, PeerRole.CUSTOMER, ws)

    assert room is manager.rooms[CALL_ID]
    assert room.room_id == f"call:{CALL_ID}"
    assert room.customer_peer is not None
    assert room.customer_peer.peer_id == CUSTOMER_ID
    assert room.employee_peer is None

    # The same room object is handed back on a second join, not recreated.
    room_again = await manager.register_peer(
        CALL_ID, EMPLOYEE_ID, PeerRole.EMPLOYEE, FakeWebSocket("employee")
    )
    assert room_again is room


async def test_register_two_peers_makes_room_ready():
    manager = SignalingManager()

    await register_pair(manager)

    room = manager.rooms[CALL_ID]
    assert room.customer_peer.peer_id == CUSTOMER_ID
    assert room.employee_peer.peer_id == EMPLOYEE_ID
    assert room.is_ready() is True


async def test_register_peer_accepts_employee_joining_first():
    manager = SignalingManager()

    await manager.register_peer(
        CALL_ID, EMPLOYEE_ID, PeerRole.EMPLOYEE, FakeWebSocket("employee")
    )

    room = manager.rooms[CALL_ID]
    assert room.employee_peer is not None
    assert room.is_ready() is False


async def test_third_peer_of_same_role_is_rejected():
    manager = SignalingManager()
    await register_pair(manager)

    with pytest.raises(RoomFull):
        await manager.register_peer(
            CALL_ID, "customer-002", PeerRole.CUSTOMER, FakeWebSocket("intruder")
        )

    with pytest.raises(RoomFull):
        await manager.register_peer(
            CALL_ID, "employee-002", PeerRole.EMPLOYEE, FakeWebSocket("intruder")
        )


async def test_failed_registration_leaves_existing_room_intact():
    manager = SignalingManager()
    customer_ws, employee_ws = await register_pair(manager)

    with pytest.raises(RoomFull):
        await manager.register_peer(
            CALL_ID, "customer-002", PeerRole.CUSTOMER, FakeWebSocket("intruder")
        )

    # The room still exists and the original peers were never evicted.
    room = manager.rooms[CALL_ID]
    assert room.customer_peer.websocket is customer_ws
    assert room.employee_peer.websocket is employee_ws
    assert room.is_ready() is True


# ---------------------------------------------------------------------------
# 5-9: message routing
# ---------------------------------------------------------------------------


async def test_message_is_sent_only_to_the_other_peer():
    """Module 3 "done when": send from one peer reaches exactly the other one."""
    manager = SignalingManager()
    customer_ws, employee_ws = await register_pair(manager)

    await manager.send_to_peer(CALL_ID, CUSTOMER_ID, make_message())

    assert len(employee_ws.sent) == 1
    assert len(customer_ws.sent) == 0

    # And routing is symmetric.
    await manager.send_to_peer(CALL_ID, EMPLOYEE_ID, make_message(MessageType.ANSWER))

    assert len(customer_ws.sent) == 1
    assert len(employee_ws.sent) == 1


async def test_outgoing_message_round_trips_through_protocol():
    manager = SignalingManager()
    _, employee_ws = await register_pair(manager)

    await manager.send_to_peer(CALL_ID, CUSTOMER_ID, make_message())

    # What came out of the manager's socket is a valid Module 1 contract message.
    parsed = validate_message(employee_ws.sent[0])
    assert parsed.type is MessageType.OFFER
    assert parsed.call_id == CALL_ID
    assert parsed.payload == {"sdp": "v=0"}
    assert json.loads(employee_ws.sent[0])["type"] == "offer"


async def test_send_to_peer_raises_room_not_found_for_unknown_call():
    """Module 3 "done when": unknown room raises instead of crashing."""
    manager = SignalingManager()
    await register_pair(manager)

    with pytest.raises(RoomNotFound):
        await manager.send_to_peer("call-does-not-exist", CUSTOMER_ID, make_message())


async def test_send_to_peer_without_other_peer_does_not_raise():
    manager = SignalingManager()
    customer_ws = FakeWebSocket("customer")
    await manager.register_peer(CALL_ID, CUSTOMER_ID, PeerRole.CUSTOMER, customer_ws)

    # Opposite peer has not joined yet -> silent no-op.
    await manager.send_to_peer(CALL_ID, CUSTOMER_ID, make_message())

    assert customer_ws.sent == []


async def test_send_from_unknown_peer_is_not_delivered():
    manager = SignalingManager()
    customer_ws, employee_ws = await register_pair(manager)

    await manager.send_to_peer(CALL_ID, "peer-not-in-room", make_message())

    assert customer_ws.sent == []
    assert employee_ws.sent == []


# ---------------------------------------------------------------------------
# 10-11: disconnect cleanup
# ---------------------------------------------------------------------------


async def test_remove_peer_is_idempotent():
    """Module 3 "done when": removing twice must not raise."""
    manager = SignalingManager()
    await register_pair(manager)

    await manager.remove_peer(CALL_ID, CUSTOMER_ID)
    await manager.remove_peer(CALL_ID, CUSTOMER_ID)  # second call is safe

    room = manager.rooms[CALL_ID]
    assert room.customer_peer is None
    assert room.employee_peer is not None

    # Also safe for an unknown peer and for an unknown room.
    await manager.remove_peer(CALL_ID, "peer-that-never-joined")
    await manager.remove_peer("call-does-not-exist", CUSTOMER_ID)

    assert CALL_ID in manager.rooms


async def test_removing_last_peer_removes_the_room():
    manager = SignalingManager()
    await register_pair(manager)

    await manager.remove_peer(CALL_ID, CUSTOMER_ID)
    await manager.remove_peer(CALL_ID, EMPLOYEE_ID)

    assert manager.rooms == {}


# ---------------------------------------------------------------------------
# 12-13: room teardown
# ---------------------------------------------------------------------------


async def test_close_room_notifies_remaining_peer_and_removes_room():
    manager = SignalingManager()
    customer_ws, _ = await register_pair(manager)
    await manager.remove_peer(CALL_ID, EMPLOYEE_ID)

    await manager.close_room(CALL_ID)

    assert len(customer_ws.sent) == 1
    notice = validate_message(customer_ws.sent[0])
    assert notice.type is MessageType.CALL_STATE
    assert notice.call_id == CALL_ID
    assert notice.payload == {"state": "ended"}

    assert CALL_ID not in manager.rooms


async def test_close_room_is_safe_for_unknown_call():
    manager = SignalingManager()

    await manager.close_room("call-does-not-exist")

    assert manager.rooms == {}


async def test_manager_does_not_import_database_layers():
    """Module 3 constraint: registry state is never persisted to PostgreSQL."""
    import app.signaling.manager as manager_module

    assert not hasattr(manager_module, "Session")
    assert not hasattr(manager_module, "get_db")


# ---------------------------------------------------------------------------
# 14: room isolation
# ---------------------------------------------------------------------------


async def test_rooms_are_isolated_between_call_ids():
    manager = SignalingManager()
    customer_ws, employee_ws = await register_pair(manager, call_id="call-001")

    other_customer_ws, other_employee_ws = await register_pair(
        manager,
        call_id="call-002",
        customer_id="customer-002",
        employee_id="employee-002",
    )

    await manager.send_to_peer("call-001", CUSTOMER_ID, make_message(call_id="call-001"))

    assert len(employee_ws.sent) == 1
    assert len(customer_ws.sent) == 0
    assert other_customer_ws.sent == []
    assert other_employee_ws.sent == []

    # Closing one room must not disturb the other.
    await manager.close_room("call-001")

    assert "call-001" not in manager.rooms
    assert "call-002" in manager.rooms
    assert other_customer_ws.sent == []
