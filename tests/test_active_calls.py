"""
/calls/active - active call state tests.

Two layers are covered:

- the endpoint's in-memory behaviour, driven through the real app with
  TestClient exactly like tests/test_signaling_websocket.py: ``get_db`` is
  overridden so no PostgreSQL is needed, and every database-derived field is
  therefore None;
- the service's join to the interaction table, using a stub session, so the
  department / journey / transfer fields are still covered without a database.

Run from the backend project root:
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_active_calls.py -q
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.routers import websocket_signaling
from app.services import calls_service
from app.signaling.room import Room

SECRET = "test-signaling-secret"
AUDIENCE = "sales-signaling"
SIGNALING_URL = "/ws/signaling"
ACTIVE_CALLS_URL = "/api/v1/calls/active"

CUSTOMER_ID = uuid.uuid4()
EMPLOYEE_ID = uuid.uuid4()

CUSTOMER_PEER_ID = f"customer:{CUSTOMER_ID}"
EMPLOYEE_PEER_ID = f"employee:{EMPLOYEE_ID}"


def make_token(subject, role, expires_in=300):
    now = datetime.now(timezone.utc)

    return jwt.encode(
        {
            "sub": str(subject),
            "role": role,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
        },
        SECRET,
        algorithm="HS256",
    )


def join_frame(call_id, role):
    return {"type": "join", "call_id": call_id, "payload": {"role": role}}


def stub_session(interaction):
    """A Session whose interaction lookup always answers with ``interaction``."""
    session = Mock()
    session.query.return_value.filter.return_value.first.return_value = interaction
    return session


@pytest.fixture(autouse=True)
def configured_secret(monkeypatch):
    monkeypatch.setattr(settings, "SIGNALING_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "SIGNALING_JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(settings, "SIGNALING_JWT_AUDIENCE", AUDIENCE)
    return SECRET


@pytest.fixture(autouse=True)
def authorize(monkeypatch):
    """Ownership is test_signaling_authorization.py's subject; here it is a pass."""
    monkeypatch.setattr(
        websocket_signaling,
        "authorize_interaction_access",
        lambda db, principal, target_id: object(),
    )


@pytest.fixture(autouse=True)
def clean_rooms():
    """The registry is process-wide, so each test starts and ends empty."""
    websocket_signaling.signaling_manager.rooms.clear()

    yield

    websocket_signaling.signaling_manager.rooms.clear()


@pytest.fixture
def client():
    """
    A TestClient with no database behind it.

    Overriding get_db with a generator yielding None is the point rather than a
    shortcut: it proves the endpoint still answers, with null database fields,
    when the signaling process cannot reach the interaction table.
    """

    def fake_get_db():
        yield None

    app.dependency_overrides[get_db] = fake_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# In-memory behaviour through the endpoint
# ---------------------------------------------------------------------------
def test_no_calls_when_no_rooms_exist(client):
    response = client.get(ACTIVE_CALLS_URL)

    assert response.status_code == 200
    assert response.json() == []


def test_call_appears_on_first_join_as_waiting(client):
    call_id = str(uuid.uuid4())

    with client.websocket_connect(
        f"{SIGNALING_URL}?access_token={make_token(CUSTOMER_ID, 'customer')}"
    ) as customer:
        customer.send_json(join_frame(call_id, "customer"))
        customer.receive_json()  # call_state: waiting

        calls = client.get(ACTIVE_CALLS_URL).json()

        assert len(calls) == 1
        call = calls[0]
        assert call["call_id"] == call_id
        assert call["state"] == "waiting"
        assert call["customer_peer_id"] == CUSTOMER_PEER_ID
        assert call["employee_peer_id"] is None
        # No database in this test, so every joined field is honestly null.
        assert call["department_id"] is None
        assert call["journey_id"] is None
        assert call["employee_id"] is None
        assert call["transfer_in_progress"] is False
        assert call["started_at"] is not None


def test_call_becomes_ready_when_second_peer_joins(client):
    call_id = str(uuid.uuid4())

    with client.websocket_connect(
        f"{SIGNALING_URL}?access_token={make_token(CUSTOMER_ID, 'customer')}"
    ) as customer:
        customer.send_json(join_frame(call_id, "customer"))
        customer.receive_json()

        with client.websocket_connect(
            f"{SIGNALING_URL}?access_token={make_token(EMPLOYEE_ID, 'employee')}"
        ) as employee:
            employee.send_json(join_frame(call_id, "employee"))
            employee.receive_json()  # ready
            customer.receive_json()  # ready

            call = client.get(ACTIVE_CALLS_URL).json()[0]

            assert call["state"] == "ready"
            assert call["employee_peer_id"] == EMPLOYEE_PEER_ID


def test_hangup_removes_the_call(client):
    call_id = str(uuid.uuid4())

    with client.websocket_connect(
        f"{SIGNALING_URL}?access_token={make_token(CUSTOMER_ID, 'customer')}"
    ) as customer:
        customer.send_json(join_frame(call_id, "customer"))
        customer.receive_json()

        with client.websocket_connect(
            f"{SIGNALING_URL}?access_token={make_token(EMPLOYEE_ID, 'employee')}"
        ) as employee:
            employee.send_json(join_frame(call_id, "employee"))
            employee.receive_json()
            customer.receive_json()

            employee.send_json({"type": "hangup", "call_id": call_id})

            assert client.get(ACTIVE_CALLS_URL).json() == []


def test_dropped_socket_leaves_the_survivor_in_the_room(client):
    """
    A room outlives one of its peers.

    The manager only discards a room once both slots are empty, so a socket that
    drops takes its own participant out and leaves the call listed - back to
    "waiting" - for as long as the other side stays connected.
    """
    call_id = str(uuid.uuid4())

    with client.websocket_connect(
        f"{SIGNALING_URL}?access_token={make_token(CUSTOMER_ID, 'customer')}"
    ) as customer:
        with client.websocket_connect(
            f"{SIGNALING_URL}?access_token={make_token(EMPLOYEE_ID, 'employee')}"
        ) as employee:
            customer.send_json(join_frame(call_id, "customer"))
            employee.send_json(join_frame(call_id, "employee"))
            customer.receive_json()
            customer.receive_json()  # waiting, then ready
            employee.receive_json()  # ready

            employee.close()

            calls = client.get(ACTIVE_CALLS_URL).json()

            assert len(calls) == 1
            assert calls[0]["call_id"] == call_id
            assert calls[0]["state"] == "waiting"
            assert calls[0]["customer_peer_id"] == CUSTOMER_PEER_ID
            assert calls[0]["employee_peer_id"] is None

    # The customer's socket closes here too, which empties the room for good.
    assert client.get(ACTIVE_CALLS_URL).json() == []


# ---------------------------------------------------------------------------
# Service-level: the join to the interaction table
# ---------------------------------------------------------------------------
def _room(call_id, created_at):
    room = Room(call_id)
    room.created_at = created_at
    websocket_signaling.signaling_manager.rooms[call_id] = room
    return room


def test_interaction_fields_and_transfer_flag_come_from_the_interaction_row():
    call_id = str(uuid.uuid4())
    interaction = SimpleNamespace(
        employee_id=EMPLOYEE_ID,
        journey_id=uuid.uuid4(),
        department_id=uuid.uuid4(),
        outcome="transferred",
    )

    _room(call_id, datetime.now(timezone.utc))

    calls = calls_service.get_active_calls(stub_session(interaction))

    assert len(calls) == 1
    assert calls[0]["employee_id"] == EMPLOYEE_ID
    assert calls[0]["journey_id"] == interaction.journey_id
    assert calls[0]["department_id"] == interaction.department_id
    assert calls[0]["transfer_in_progress"] is True


def test_completed_interaction_is_not_a_transfer_in_progress():
    call_id = str(uuid.uuid4())
    interaction = SimpleNamespace(
        employee_id=EMPLOYEE_ID,
        journey_id=uuid.uuid4(),
        department_id=uuid.uuid4(),
        outcome="completed",
    )

    _room(call_id, datetime.now(timezone.utc))

    calls = calls_service.get_active_calls(stub_session(interaction))

    assert calls[0]["transfer_in_progress"] is False


def test_calls_are_ordered_oldest_first():
    older_call_id = str(uuid.uuid4())
    newer_call_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    _room(newer_call_id, now)
    _room(older_call_id, now - timedelta(minutes=5))

    calls = calls_service.get_active_calls(None)

    assert [call["call_id"] for call in calls] == [older_call_id, newer_call_id]


def test_missing_interaction_row_still_reports_the_call():
    call_id = str(uuid.uuid4())

    _room(call_id, datetime.now(timezone.utc))

    calls = calls_service.get_active_calls(stub_session(None))

    assert len(calls) == 1
    assert calls[0]["department_id"] is None
    assert calls[0]["transfer_in_progress"] is False


def test_non_uuid_call_id_is_reported_without_database_fields():
    """
    A room key that is not an interaction UUID must not raise.

    The UUID parse fails, so the interaction lookup is never issued and the call
    is still reported - minus the fields only the database could have filled in.
    """
    session = Mock()
    session.query.side_effect = AssertionError("no lookup for a non-UUID call id")

    _room("not-a-uuid", datetime.now(timezone.utc))

    calls = calls_service.get_active_calls(session)

    assert len(calls) == 1
    assert calls[0]["call_id"] == "not-a-uuid"
    assert calls[0]["department_id"] is None
    assert calls[0]["transfer_in_progress"] is False
