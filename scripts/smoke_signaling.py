r"""
Live signaling smoke test — two real WebSocket clients against a running server.

The pytest suite drives the endpoint through Starlette's TestClient, which is
an in-process transport: it proves the routing logic but never exercises a real
TCP upgrade, the query-string token, or uvicorn's frame handling. This script
covers that gap. It is not a replacement for the tests and is not run by
pytest; it is the manual acceptance check from the signaling build plan.

What it does
------------
1. Picks one real interaction from the database whose journey has a customer
   and whose row has an assigned employee, then mints a signaling token for
   each side. Read-only — nothing is written to any table.
2. Opens two real sockets, joins them into the same call, and walks the full
   protocol: ready -> offer -> answer -> ice_candidate -> hangup.
3. Opens a fresh pair and kills one socket without a hangup, asserting the
   survivor receives call_state {"state": "peer_left"}.

Prerequisites
-------------
- SIGNALING_JWT_SECRET is set in .env (the endpoint fails closed without it)
- The database has at least one interaction with a journey customer and an
  assigned employee — every row the REST API creates has both.
- pip install websockets

Run from the backend project root, against a server you started yourself:
    uvicorn app.main:app --port 8000
    .\.venv\Scripts\python.exe scripts\smoke_signaling.py

Or let this script host the server itself, which is handy when no server is
running yet (it binds 127.0.0.1 only):
    .\.venv\Scripts\python.exe scripts\smoke_signaling.py --serve --port 8001
"""

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

import jwt
import websockets

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal  # noqa: E402
from app.models.interaction import Interaction  # noqa: E402
from app.models.journey import Journey  # noqa: E402

HOST = os.environ.get("SMOKE_HOST", "127.0.0.1:8000")
WS_URL = f"ws://{HOST}/ws/signaling"


def point_at(host: str) -> None:
    """Retarget every URL the scenarios build, for when this script hosts the server."""
    global HOST, WS_URL

    HOST = host
    WS_URL = f"ws://{HOST}/ws/signaling"


def start_server(port: int):
    """
    Boot the app on a background thread and wait until it is accepting traffic.

    Lets the smoke test run when no uvicorn is already up. Binds loopback only,
    so nothing is exposed beyond this machine.
    """
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(
            "app.main:app",
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 30

    while not server.started:
        if time.monotonic() > deadline:
            print(f"Server on port {port} did not start within 30s.")
            sys.exit(2)

        if not thread.is_alive():
            print(f"Server thread died before it began serving on port {port}.")
            sys.exit(2)

        time.sleep(0.1)

    return server

# How long to wait for a frame the server is expected to send unprompted.
RECEIVE_TIMEOUT = 5.0

_passed = 0
_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed

    if condition:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}" + (f" -- {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{title}")


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
def load_settings():
    """Read the signaling settings the same way the app does."""
    from app.core.config import settings

    if not settings.SIGNALING_JWT_SECRET:
        print("SIGNALING_JWT_SECRET is not set in .env — the server would refuse every socket.")
        sys.exit(2)

    return settings


def pick_interaction():
    """
    Return (call_id, customer_id, employee_id) for a real, joinable interaction.

    Read-only: the ownership check the server runs is the same query, so a row
    that satisfies this is a row both peers can legitimately join.
    """
    db = SessionLocal()

    try:
        row = (
            db.query(Interaction.interaction_id, Interaction.employee_id, Journey.customer_id)
            .join(Journey, Interaction.journey_id == Journey.journey_id)
            .filter(
                Interaction.employee_id.isnot(None),
                Journey.customer_id.isnot(None),
            )
            .first()
        )
    finally:
        db.close()

    if row is None:
        print(
            "No usable interaction found. Create one through the REST API first "
            "(a journey with a customer, plus a started interaction with an employee)."
        )
        sys.exit(2)

    # The query's column order is not the order the callers want: name the
    # parts rather than returning row[i], which silently swaps the two roles.
    interaction_id, employee_id, customer_id = row

    if str(customer_id) == str(employee_id):
        print("The first usable interaction has the same customer and employee; pick another.")
        sys.exit(2)

    return str(interaction_id), str(customer_id), str(employee_id)


def make_token(settings, subject: str, role: str) -> str:
    import time

    return jwt.encode(
        {
            "sub": subject,
            "role": role,
            "aud": settings.SIGNALING_JWT_AUDIENCE,
            "exp": int(time.time()) + 300,
        },
        settings.SIGNALING_JWT_SECRET,
        algorithm=settings.SIGNALING_JWT_ALGORITHM,
    )


def url_for(token: str) -> str:
    return f"{WS_URL}?access_token={token}"


async def receive(socket, timeout: float = RECEIVE_TIMEOUT) -> dict:
    raw = await asyncio.wait_for(socket.recv(), timeout=timeout)
    return json.loads(raw)


async def receive_until_type(socket, message_type: str, timeout: float = RECEIVE_TIMEOUT) -> dict:
    """Skip past frames of other types; return the first frame of ``message_type``."""
    while True:
        frame = await receive(socket, timeout)

        if frame.get("type") == message_type:
            return frame


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
async def scenario_full_call(settings, call_id, customer_token, employee_token):
    """join -> ready -> offer -> answer -> ice_candidate -> hangup."""
    section("1. Full call flow between two real clients")

    async with websockets.connect(url_for(customer_token)) as customer:
        await customer.send(
            json.dumps({"type": "join", "call_id": call_id, "payload": {"role": "customer"}})
        )

        waiting = await receive(customer)
        check(
            "first joiner is told the call is waiting",
            waiting.get("type") == "call_state" and waiting["payload"].get("state") == "waiting",
            f"got {waiting}",
        )

        async with websockets.connect(url_for(employee_token)) as employee:
            await employee.send(
                json.dumps({"type": "join", "call_id": call_id, "payload": {"role": "employee"}})
            )

            customer_ready = await receive_until_type(customer, "ready")
            employee_ready = await receive_until_type(employee, "ready")
            check(
                "both peers are told the call is ready",
                customer_ready["payload"].get("state") == "ready"
                and employee_ready["payload"].get("state") == "ready",
                f"{customer_ready} / {employee_ready}",
            )

            # ---- offer: customer -> employee --------------------------------
            sdp = "v=0\r\no=- 4611731400430051336 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n"
            await customer.send(
                json.dumps(
                    {
                        "type": "offer",
                        "call_id": call_id,
                        "payload": {"sdp": sdp},
                        # A deliberately wrong claim: the server must ignore it.
                        "sender": "employee:forged",
                    }
                )
            )

            offer = await receive_until_type(employee, "offer")
            check("offer reaches the other client", offer["type"] == "offer")
            check(
                "offer payload arrives byte-for-byte",
                offer["payload"].get("sdp") == sdp,
                f"got {offer['payload'].get('sdp')!r}",
            )
            check(
                "client-supplied sender is overwritten with the authenticated peer",
                offer.get("sender", "").startswith("customer:")
                and offer.get("sender") != "employee:forged",
                f"got {offer.get('sender')!r}",
            )

            # ---- answer: employee -> customer -------------------------------
            await employee.send(
                json.dumps(
                    {
                        "type": "answer",
                        "call_id": call_id,
                        "payload": {"sdp": "v=0\r\no=- 99 2 IN IP4 127.0.0.1\r\n"},
                    }
                )
            )

            answer = await receive_until_type(customer, "answer")
            check(
                "answer comes back the other way",
                answer.get("sender", "").startswith("employee:"),
                f"got {answer.get('sender')!r}",
            )

            # ---- ice candidate ---------------------------------------------
            await customer.send(
                json.dumps(
                    {
                        "type": "ice_candidate",
                        "call_id": call_id,
                        "payload": {
                            "candidate": "candidate:842163049 1 udp 1677729535 203.0.113.7 55011 typ srflx",
                            "sdpMid": "0",
                            "sdpMLineIndex": 0,
                        },
                    }
                )
            )

            ice = await receive_until_type(employee, "ice_candidate")
            check(
                "ice candidate arrives with its fields intact",
                ice["payload"].get("sdpMLineIndex") == 0
                and ice["payload"].get("sdpMid") == "0",
                f"got {ice['payload']}",
            )

            # ---- malformed frame does not kill the socket -------------------
            await customer.send("{not json")
            error = await receive(customer)
            check(
                "a malformed frame is reported and the socket survives",
                error.get("type") == "error"
                and error["payload"].get("code") == "INVALID_MESSAGE",
                f"got {error}",
            )

            await customer.send(
                json.dumps({"type": "offer", "call_id": call_id, "payload": {"sdp": "after-error"}})
            )
            recovered = await receive_until_type(employee, "offer")
            check(
                "the call still works after the bad frame",
                recovered["payload"].get("sdp") == "after-error",
            )

            # ---- hangup ----------------------------------------------------
            await customer.send(
                json.dumps({"type": "hangup", "call_id": call_id, "payload": {}})
            )

            ended = await receive_until_type(employee, "call_state")
            check(
                "the other peer is told the call ended",
                ended["payload"].get("state") == "ended",
                f"got {ended}",
            )


async def scenario_abrupt_disconnect(settings, call_id, customer_token, employee_token):
    """One client vanishes without a hangup; the survivor is notified."""
    section("2. Abrupt disconnect")

    async with websockets.connect(url_for(customer_token)) as customer:
        await customer.send(
            json.dumps({"type": "join", "call_id": call_id, "payload": {"role": "customer"}})
        )
        await receive_until_type(customer, "call_state")

        employee = await websockets.connect(url_for(employee_token))
        await employee.send(
            json.dumps({"type": "join", "call_id": call_id, "payload": {"role": "employee"}})
        )

        await receive_until_type(customer, "ready")
        await receive_until_type(employee, "ready")

        # Hard kill: no close frame, no hangup.
        await employee.close()

        notice = await receive_until_type(customer, "call_state")
        check(
            "the survivor is pushed a peer_left notice",
            notice["payload"].get("state") == "peer_left",
            f"got {notice}",
        )

        # The server must still be healthy after the drop.
        await customer.send(
            json.dumps({"type": "offer", "call_id": call_id, "payload": {"sdp": "v=0"}})
        )
        error = await receive(customer)
        check(
            "speaking after the drop reports PEER_NOT_CONNECTED, not a crash",
            error.get("type") == "error"
            and error["payload"].get("code") == "PEER_NOT_CONNECTED",
            f"got {error}",
        )

        await customer.send(json.dumps({"type": "hangup", "call_id": call_id, "payload": {}}))


async def scenario_rejections(settings, call_id, customer_token, employee_token):
    """The failures a client team is most likely to hit."""
    section("3. Rejections")

    # No token at all.
    try:
        async with websockets.connect(WS_URL) as socket:
            frame = await receive(socket)
            check(
                "a socket with no token gets AUTH_FAILED",
                frame.get("type") == "error" and frame["payload"].get("code") == "AUTH_FAILED",
                f"got {frame}",
            )
    except Exception as exc:  # a server that closes before answering also fails the check
        check("a socket with no token gets AUTH_FAILED", False, repr(exc))

    # Valid token, but not a party to this interaction.
    stranger = make_token(settings, "00000000-0000-0000-0000-0000000000ff", "customer")
    async with websockets.connect(url_for(stranger)) as socket:
        await socket.send(
            json.dumps({"type": "join", "call_id": call_id, "payload": {"role": "customer"}})
        )
        frame = await receive(socket)
        check(
            "a stranger cannot join someone else's call",
            frame.get("type") == "error" and frame["payload"].get("code") == "AUTH_FAILED",
            f"got {frame}",
        )

    # Correct owner, wrong role for the token it was issued for.
    async with websockets.connect(url_for(customer_token)) as socket:
        await socket.send(
            json.dumps({"type": "join", "call_id": call_id, "payload": {"role": "employee"}})
        )
        frame = await receive(socket)
        check(
            "a token cannot claim the other role",
            frame.get("type") == "error" and frame["payload"].get("code") == "AUTH_FAILED",
            f"got {frame}",
        )

    # Offer before join.
    async with websockets.connect(url_for(customer_token)) as socket:
        await socket.send(json.dumps({"type": "offer", "call_id": call_id, "payload": {"sdp": "v=0"}}))
        frame = await receive(socket)
        check(
            "an offer before a join is refused",
            frame.get("type") == "error" and frame["payload"].get("code") == "INVALID_MESSAGE",
            f"got {frame}",
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main(serve: bool = False, port: int = 8001) -> int:
    if serve:
        point_at(f"127.0.0.1:{port}")
        start_server(port)
        print(f"Started a server on 127.0.0.1:{port} for this run.")

    settings = load_settings()
    call_id, customer_id, employee_id = pick_interaction()

    print(f"Server:      {WS_URL}")
    print(f"Interaction: {call_id}")
    print(f"Customer:    {customer_id}")
    print(f"Employee:    {employee_id}")

    customer_token = make_token(settings, customer_id, "customer")
    employee_token = make_token(settings, employee_id, "employee")

    scenarios = (
        ("full call flow", scenario_full_call),
        ("abrupt disconnect", scenario_abrupt_disconnect),
        ("rejections", scenario_rejections),
    )

    for name, scenario in scenarios:
        # One scenario blowing up (a socket closed early, a timeout) must not
        # hide the result of the ones after it.
        try:
            await scenario(settings, call_id, customer_token, employee_token)
        except OSError as exc:
            print(f"\nCould not reach the server at {WS_URL}: {exc}")
            print("Start it first:  uvicorn app.main:app --port 8000")
            return 2
        except asyncio.TimeoutError:
            check(f"{name}: no frame arrived before the timeout", False)
        except Exception as exc:
            check(f"{name}: raised {type(exc).__name__}", False, str(exc))

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--serve",
        action="store_true",
        help="host the app on a background thread instead of using a running server",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="port for --serve (default: 8001, so a dev server on 8000 is left alone)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(main(serve=args.serve, port=args.port)))
