"""
Signaling Module 4 - /ws/signaling endpoint tests.

These tests drive the real FastAPI app with Starlette's TestClient, which runs
the whole websocket stack in-process. Everything is local: no PostgreSQL (the
``get_db`` dependency is overridden and the ownership query is stubbed), no
network, no browsers.

Both peers are connected inside a single ``with TestClient(app)`` block so that
every socket session shares one event loop - that is what makes peer-to-peer
routing observable, since the server writes to the *other* peer's socket from
the task that received the frame.

What is covered:
- join handshake: waiting -> ready, role must match the token, call ids must be
  real and consistent, and the interaction must belong to the caller;
- authentication: missing / empty / garbage / wrong-secret / expired /
  wrong-audience tokens and unconfigured secrets all fail closed;
- routing: offer, answer and ICE candidates reach only the opposite peer of the
  same call, with the envelope stamped by the server;
- failures: malformed frames and impossible targets are reported as error
  envelopes without killing the socket, and hangup / disconnect tear the room
  down correctly.

Run from the backend project root:
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_signaling_websocket.py -q
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.routers import websocket_signaling
from app.signaling.exceptions import SignalingError

SECRET = "test-signaling-secret"
AUDIENCE = "sales-signaling"
SIGNALING_URL = "/ws/signaling"

CUSTOMER_ID = uuid.uuid4()
EMPLOYEE_ID = uuid.uuid4()

CUSTOMER_PEER_ID = f"customer:{CUSTOMER_ID}"
EMPLOYEE_PEER_ID = f"employee:{EMPLOYEE_ID}"


def make_token(subject, role, secret=SECRET, audience=AUDIENCE, expires_in=300):
    """Mint the HS256 token the identity layer hands to a signaling client."""
    now = datetime.now(timezone.utc)

    return jwt.encode(
        {
            "sub": str(subject),
            "role": role,
            "aud": audience,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
        },
        secret,
        algorithm="HS256",
    )


def signaling_url(token=None):
    """Build the handshake URL; the token travels in the query string."""
    if token is None:
        return SIGNALING_URL

    return f"{SIGNALING_URL}?access_token={token}"


def join_frame(call_id, role):
    return {"type": "join", "call_id": call_id, "payload": {"role": role}}


def error_code(frame):
    """Assert the Module 1 error envelope and return its wire code."""
    assert frame["type"] == "error"
    assert set(frame["payload"]) == {"code", "message"}
    assert frame["payload"]["message"]
    return frame["payload"]["code"]


@pytest.fixture
def interaction_id():
    return uuid.uuid4()


@pytest.fixture
def call_id(interaction_id):
    """The call id is the interaction UUID, as a string."""
    return str(interaction_id)


@pytest.fixture(autouse=True)
def configured_secret(monkeypatch):
    """Give the app a known signing secret, without depending on .env."""
    monkeypatch.setattr(settings, "SIGNALING_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "SIGNALING_JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(settings, "SIGNALING_JWT_AUDIENCE", AUDIENCE)
    return SECRET


@pytest.fixture
def authorize(monkeypatch):
    """
    Stub the DB-backed ownership check and record who was authorised.

    tests/test_signaling_authorization.py covers the SQL itself; here we only
    need to prove that the endpoint asks it before creating a room.
    """
    calls = []

    def fake_authorize(db, principal, target_id):
        calls.append((principal, target_id))
        return object()

    monkeypatch.setattr(websocket_signaling, "authorize_interaction_access", fake_authorize)
    return calls


@pytest.fixture
def client():
    """A TestClient whose event loop is shared by every websocket session."""
    websocket_signaling.signaling_manager.rooms.clear()

    def fake_get_db():
        yield None

    app.dependency_overrides[get_db] = fake_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        websocket_signaling.signaling_manager.rooms.clear()


def connect(client, token):
    return client.websocket_connect(signaling_url(token))


# ---------------------------------------------------------------------------
# Join handshake: waiting -> ready, then peer-to-peer routing
# ---------------------------------------------------------------------------
def test_waiting_then_ready_and_exact_offer_routing(client, call_id, authorize):
    customer_token = make_token(CUSTOMER_ID, "customer")
    employee_token = make_token(EMPLOYEE_ID, "employee")

    with connect(client, customer_token) as customer:
        customer.send_json(join_frame(call_id, "customer"))

        # Alone in the room: the caller is told to wait for the other side.
        waiting = customer.receive_json()
        assert waiting["type"] == "call_state"
        assert waiting["payload"]["state"] == "waiting"
        assert waiting["call_id"] == call_id

        with connect(client, employee_token) as employee:
            employee.send_json(join_frame(call_id, "employee"))

            # The join that completes the pair wakes *both* sides up.
            assert employee.receive_json()["type"] == "ready"
            assert customer.receive_json()["type"] == "ready"

            room = websocket_signaling.signaling_manager.rooms[call_id]
            assert room.is_ready() is True

            # The offer is forwarded verbatim, with `sender` overwritten by the
            # server: a client's own claim about who it is is never trusted.
            customer.send_json(
                {
                    "type": "offer",
                    "call_id": call_id,
                    "sender": "customer:spoofed",
                    "payload": {"sdp": "v=0\r\n"},
                }
            )

            offer = employee.receive_json()
            assert offer["type"] == "offer"
            assert offer["sender"] == CUSTOMER_PEER_ID
            assert offer["payload"] == {"sdp": "v=0\r\n"}

            # ...and the answer comes back the other way, stamped likewise.
            employee.send_json(
                {
                    "type": "answer",
                    "call_id": call_id,
                    "payload": {"sdp": "v=0\r\nanswer"},
                }
            )

            answer = customer.receive_json()
            assert answer["type"] == "answer"
            assert answer["sender"] == EMPLOYEE_PEER_ID
            assert answer["payload"] == {"sdp": "v=0\r\nanswer"}

            # ICE candidates flow in both directions too.
            employee.send_json(
                {
                    "type": "ice_candidate",
                    "call_id": call_id,
                    "payload": {"candidate": "candidate:1 1 udp 2113"},
                }
            )

            ice = customer.receive_json()
            assert ice["type"] == "ice_candidate"
            assert ice["sender"] == EMPLOYEE_PEER_ID

            customer.send_json(
                {
                    "type": "ice_candidate",
                    "call_id": call_id,
                    "payload": {"candidate": "candidate:2 1 udp 2114"},
                }
            )

            ice_back = employee.receive_json()
            assert ice_back["type"] == "ice_candidate"
            assert ice_back["sender"] == CUSTOMER_PEER_ID

    # Both peers asked to be let into the interaction they claim to be in.
    assert [principal.peer_id for principal, _ in authorize] == [
        CUSTOMER_PEER_ID,
        EMPLOYEE_PEER_ID,
    ]
    assert {target for _, target in authorize} == {uuid.UUID(call_id)}


def test_outgoing_envelope_is_stamped_by_the_server(client, call_id, authorize):
    customer_token = make_token(CUSTOMER_ID, "customer")
    employee_token = make_token(EMPLOYEE_ID, "employee")

    with connect(client, customer_token) as customer:
        customer.send_json(join_frame(call_id, "customer"))
        customer.receive_json()

        with connect(client, employee_token) as employee:
            employee.send_json(join_frame(call_id, "employee"))
            employee.receive_json()
            customer.receive_json()

            customer.send_json(
                {
                    "type": "offer",
                    "call_id": str(uuid.uuid4()),  # the client's wrong idea
                    "interaction_id": str(uuid.uuid4()),  # ...and another
                    "sender": "somebody-else",
                    "payload": {"sdp": "v=0"},
                }
            )

            offer = employee.receive_json()

    # The room, not the client, decides the identity of a message.
    assert offer["call_id"] == call_id
    assert offer["interaction_id"] == call_id
    assert offer["sender"] == CUSTOMER_PEER_ID
    assert offer["target"] == EMPLOYEE_PEER_ID


def test_explicit_target_must_be_the_other_peer_of_the_same_call(client, call_id, authorize):
    customer_token = make_token(CUSTOMER_ID, "customer")
    employee_token = make_token(EMPLOYEE_ID, "employee")

    with connect(client, customer_token) as customer:
        customer.send_json(join_frame(call_id, "customer"))
        customer.receive_json()

        with connect(client, employee_token) as employee:
            employee.send_json(join_frame(call_id, "employee"))
            employee.receive_json()
            customer.receive_json()

            # Naming somebody who is not this call's other peer is refused.
            customer.send_json(
                {
                    "type": "offer",
                    "call_id": call_id,
                    "target": f"employee:{uuid.uuid4()}",
                    "payload": {"sdp": "v=0"},
                }
            )

            assert error_code(customer.receive_json()) == "PEER_NOT_CONNECTED"

            # Naming the real peer is accepted.
            customer.send_json(
                {
                    "type": "offer",
                    "call_id": call_id,
                    "target": EMPLOYEE_PEER_ID,
                    "payload": {"sdp": "v=0"},
                }
            )

            assert employee.receive_json()["sender"] == CUSTOMER_PEER_ID


def test_talking_before_the_other_peer_arrives_is_reported_not_fatal(client, call_id, authorize):
    """A frame with nobody to receive it is an error the caller can retry."""
    with connect(client, make_token(CUSTOMER_ID, "customer")) as websocket:
        websocket.send_json(join_frame(call_id, "customer"))
        websocket.receive_json()

        for _ in range(2):
            websocket.send_json(
                {"type": "offer", "call_id": call_id, "payload": {"sdp": "v=0"}}
            )
            assert error_code(websocket.receive_json()) == "PEER_NOT_CONNECTED"

        assert websocket_signaling.signaling_manager.rooms[call_id].employee_peer is None


# ---------------------------------------------------------------------------
# Authentication: the query-string token is the only identity
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        "not-a-jwt",
        make_token(CUSTOMER_ID, "customer", secret="the-wrong-secret"),
        make_token(CUSTOMER_ID, "customer", expires_in=-60),
        make_token(CUSTOMER_ID, "customer", audience="someone-elses-audience"),
        make_token(CUSTOMER_ID, "admin"),
    ],
    ids=[
        "missing",
        "empty",
        "garbage",
        "wrong-secret",
        "expired",
        "wrong-audience",
        "forbidden-role",
    ],
)
def test_sockets_without_a_valid_token_fail_with_auth_failed(client, token):
    with connect(client, token) as websocket:
        error = websocket.receive_json()

        assert error_code(error) == "AUTH_FAILED"

        if token:  # the credential is never echoed back to the caller
            assert token not in json.dumps(error)

    assert websocket_signaling.signaling_manager.rooms == {}


def test_unconfigured_secret_fails_closed(client, monkeypatch):
    monkeypatch.setattr(settings, "SIGNALING_JWT_SECRET", None)

    with connect(client, make_token(CUSTOMER_ID, "customer")) as websocket:
        assert error_code(websocket.receive_json()) == "AUTH_FAILED"


# ---------------------------------------------------------------------------
# Join validation: contract, role and ownership
# ---------------------------------------------------------------------------
def test_join_must_be_the_first_frame(client, authorize):
    with connect(client, make_token(CUSTOMER_ID, "customer")) as websocket:
        websocket.send_json(
            {"type": "offer", "call_id": str(uuid.uuid4()), "payload": {"sdp": "v=0"}}
        )

        assert error_code(websocket.receive_json()) == "INVALID_MESSAGE"

    assert authorize == []
    assert websocket_signaling.signaling_manager.rooms == {}


def test_malformed_json_as_the_first_frame_is_rejected(client, authorize):
    with connect(client, make_token(CUSTOMER_ID, "customer")) as websocket:
        websocket.send_text("{")

        assert error_code(websocket.receive_json()) == "INVALID_MESSAGE"

    assert websocket_signaling.signaling_manager.rooms == {}


@pytest.mark.parametrize(
    "frame",
    [
        {"type": "join", "call_id": "not-a-uuid", "payload": {"role": "customer"}},
        {"type": "join", "call_id": "6f1d0f0a-1a4f-4c6b-9d3e-0a1b2c3d4e5f", "payload": {}},
        {
            "type": "join",
            "call_id": "6f1d0f0a-1a4f-4c6b-9d3e-0a1b2c3d4e5f",
            "payload": {"role": "admin"},
        },
        {"type": "join", "payload": {"role": "customer"}},
    ],
    ids=["call-id-not-a-uuid", "role-missing", "role-not-a-known-role", "call-id-missing"],
)
def test_join_frames_that_break_the_contract_are_rejected(client, frame, authorize):
    with connect(client, make_token(CUSTOMER_ID, "customer")) as websocket:
        websocket.send_json(frame)

        assert error_code(websocket.receive_json()) == "INVALID_MESSAGE"

    assert websocket_signaling.signaling_manager.rooms == {}


def test_join_with_inconsistent_call_and_interaction_ids_is_rejected(
    client, call_id, authorize
):
    """`call_id` and `interaction_id` denote the same interaction: no guessing."""
    with connect(client, make_token(CUSTOMER_ID, "customer")) as websocket:
        websocket.send_json(
            {
                "type": "join",
                "call_id": call_id,
                "interaction_id": str(uuid.uuid4()),
                "payload": {"role": "customer"},
            }
        )

        assert error_code(websocket.receive_json()) == "INVALID_MESSAGE"


def test_join_role_must_match_the_role_of_the_token(client, call_id, authorize):
    # The token says "customer"; the client claims to be the employee.
    with connect(client, make_token(CUSTOMER_ID, "customer")) as websocket:
        websocket.send_json(join_frame(call_id, "employee"))

        assert error_code(websocket.receive_json()) == "AUTH_FAILED"

    # A refused join never reaches the ownership check or the room registry.
    assert authorize == []
    assert websocket_signaling.signaling_manager.rooms == {}


def test_ownership_denial_is_reported_as_auth_failed(client, call_id, monkeypatch):
    def deny(db, principal, target_id):
        raise SignalingError(
            "The authenticated peer cannot access this interaction.",
            code="AUTH_FAILED",
        )

    monkeypatch.setattr(websocket_signaling, "authorize_interaction_access", deny)

    with connect(client, make_token(CUSTOMER_ID, "customer")) as websocket:
        websocket.send_json(join_frame(call_id, "customer"))

        assert error_code(websocket.receive_json()) == "AUTH_FAILED"

    # Nothing is registered before ownership is proven.
    assert websocket_signaling.signaling_manager.rooms == {}


def test_second_peer_in_the_same_role_slot_is_refused(client, call_id, authorize):
    other_customer = make_token(uuid.uuid4(), "customer")

    with connect(client, make_token(CUSTOMER_ID, "customer")) as first:
        first.send_json(join_frame(call_id, "customer"))
        first.receive_json()

        with connect(client, other_customer) as second:
            second.send_json(join_frame(call_id, "customer"))

            assert error_code(second.receive_json()) == "ROOM_FULL"

            # The peer that was already in the room was neither evicted nor
            # replaced by the newcomer.
            room = websocket_signaling.signaling_manager.rooms[call_id]
            assert room.customer_peer.peer_id == CUSTOMER_PEER_ID
            assert room.employee_peer is None

            first.send_json({"type": "offer", "call_id": call_id, "payload": {}})
            assert error_code(first.receive_json()) == "PEER_NOT_CONNECTED"


def test_a_client_cannot_forge_server_side_call_state(client, call_id, authorize):
    """A peer may only send the types listed in the routing contract."""
    with connect(client, make_token(CUSTOMER_ID, "customer")) as websocket:
        websocket.send_json(join_frame(call_id, "customer"))
        websocket.receive_json()

        # `call_state` and `ready` are server -> client only.
        for forged in ("call_state", "ready"):
            websocket.send_json({"type": forged, "call_id": call_id, "payload": {}})
            assert error_code(websocket.receive_json()) == "INVALID_MESSAGE"

        # ...and a second join on the same socket is refused too.
        websocket.send_json(join_frame(call_id, "customer"))
        assert error_code(websocket.receive_json()) == "INVALID_MESSAGE"

        # The original registration is untouched and the socket still works.
        room = websocket_signaling.signaling_manager.rooms[call_id]
        assert room.customer_peer.peer_id == CUSTOMER_PEER_ID

        websocket.send_json({"type": "offer", "call_id": call_id, "payload": {}})
        assert error_code(websocket.receive_json()) == "PEER_NOT_CONNECTED"


@pytest.mark.parametrize(
    "frame",
    [
        "{",
        "[]",
        '{"payload": {"sdp": "v=0"}}',
        '{"type": "nonsense", "call_id": "6f1d0f0a-1a4f-4c6b-9d3e-0a1b2c3d4e5f", "payload": {}}',
        '{"type": "offer", "call_id": "6f1d0f0a-1a4f-4c6b-9d3e-0a1b2c3d4e5f", "payload": "v=0"}',
    ],
    ids=[
        "truncated-json",
        "json-array",
        "missing-type-and-call-id",
        "unknown-type",
        "payload-is-not-an-object",
    ],
)
def test_malformed_routable_frames_never_kill_the_socket(client, call_id, authorize, frame):
    with connect(client, make_token(CUSTOMER_ID, "customer")) as websocket:
        websocket.send_json(join_frame(call_id, "customer"))
        websocket.receive_json()

        websocket.send_text(frame)
        assert error_code(websocket.receive_json()) == "INVALID_MESSAGE"

        # Still an authenticated, registered participant.
        assert call_id in websocket_signaling.signaling_manager.rooms


# ---------------------------------------------------------------------------
# Hangup and disconnect: how a call ends
# ---------------------------------------------------------------------------
def test_hangup_tells_the_other_peer_the_call_ended(client, call_id, authorize):
    with connect(client, make_token(CUSTOMER_ID, "customer")) as customer:
        customer.send_json(join_frame(call_id, "customer"))
        customer.receive_json()

        with connect(client, make_token(EMPLOYEE_ID, "employee")) as employee:
            employee.send_json(join_frame(call_id, "employee"))
            employee.receive_json()
            customer.receive_json()

            # The customer hangs up; the employee is the one who needs telling.
            customer.send_json({"type": "hangup", "call_id": call_id, "payload": {}})

            ended = employee.receive_json()
            assert ended["type"] == "call_state"
            assert ended["payload"]["state"] == "ended"
            assert ended["call_id"] == call_id

    # The room is gone: there is nothing left for a late frame to arrive at.
    assert websocket_signaling.signaling_manager.rooms == {}


def test_a_peer_that_disconnects_is_removed_from_the_room(client, call_id, authorize):
    with connect(client, make_token(CUSTOMER_ID, "customer")) as customer:
        customer.send_json(join_frame(call_id, "customer"))
        customer.receive_json()

        with connect(client, make_token(EMPLOYEE_ID, "employee")) as employee:
            employee.send_json(join_frame(call_id, "employee"))
            employee.receive_json()
            customer.receive_json()

        # Leaving the block closes the employee's socket. The endpoint's
        # cleanup has finished by the time TestClient hands control back.
        room = websocket_signaling.signaling_manager.rooms[call_id]
        assert room.employee_peer is None
        assert room.customer_peer.peer_id == CUSTOMER_PEER_ID

        # The survivor is told, the next time it speaks, that it is alone.
        customer.send_json({"type": "offer", "call_id": call_id, "payload": {}})
        assert error_code(customer.receive_json()) == "PEER_NOT_CONNECTED"

    # The last peer to leave takes the room with it.
    assert websocket_signaling.signaling_manager.rooms == {}


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
def mounted_paths(app_or_router):
    """Collect every route path mounted on the app, nested routers included."""
    paths = set()
    stack = list(getattr(app_or_router, "routes", []))

    while stack:
        route = stack.pop()

        path = getattr(route, "path", None)
        if path is not None:
            paths.add(path)

        # FastAPI keeps `include_router(...)` results as nested router objects
        # rather than flattening them into `app.routes`.
        stack.extend(getattr(route, "routes", []) or [])
        inner_router = getattr(route, "original_router", None)
        if inner_router is not None:
            stack.extend(getattr(inner_router, "routes", []) or [])

    return paths


def test_the_signaling_route_is_mounted_on_the_app():
    paths = mounted_paths(app)

    assert SIGNALING_URL in paths
    assert "/health" in paths
