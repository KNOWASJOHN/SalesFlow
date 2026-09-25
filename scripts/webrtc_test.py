r"""
Manual WebRTC test harness — drives a real audio call between two browser tabs.

Serves one page over http://127.0.0.1 (a secure context, so getUserMedia works)
and mints the signaling tokens that page needs. Everything else — the WebSocket,
the SDP exchange, ICE, live audio — happens in the browser against the real
signaling server, which must already be running:

    uvicorn app.main:app --reload          # port 8000, the page connects here

Then:

    .\.venv\Scripts\python.exe scripts\webrtc_test.py

Open the two printed URLs in two tabs (or two browsers), press Connect in each,
and allow the microphone. Same machine needs no STUN; see ICE_SERVERS in
webrtc_test.html for the two-machine case.
"""

import argparse
import importlib.util
import json
import sys
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import jwt

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings  # noqa: E402

PAGE = SCRIPTS_DIR / "webrtc_test.html"

# Long enough to open two tabs, allow two mic prompts, and connect; short
# enough that a leaked token is not useful for long.
TOKEN_TTL_SECONDS = 3600

ROLES = ("customer", "employee")


def _load_smoke_module():
    """
    Reuse the smoke test's interaction picker so both harnesses agree on what
    counts as a joinable interaction instead of drifting apart.
    """
    spec = importlib.util.spec_from_file_location(
        "smoke_signaling", SCRIPTS_DIR / "smoke_signaling.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_token(subject: str, role: str) -> str:
    return jwt.encode(
        {
            "sub": subject,
            "role": role,
            "aud": settings.SIGNALING_JWT_AUDIENCE,
            "exp": int(time.time()) + TOKEN_TTL_SECONDS,
        },
        settings.SIGNALING_JWT_SECRET,
        algorithm=settings.SIGNALING_JWT_ALGORITHM,
    )


class Handler(BaseHTTPRequestHandler):
    # Set once at startup so both tabs are handed the same call.
    call_id = None
    customer_id = None
    employee_id = None

    def log_message(self, fmt, *args):  # quieter console; the browser has the log
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def do_GET(self):
        route = urlparse(self.path)

        if route.path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            return

        if route.path == "/tokens":
            role = (parse_qs(route.query).get("role") or [""])[0]

            if role not in ROLES:
                self._json(400, {"error": f"role must be one of {ROLES}"})
                return

            subject = self.employee_id if role == "employee" else self.customer_id

            self._json(
                200,
                {
                    "token": make_token(subject, role),
                    "call_id": self.call_id,
                    "peer_id": f"{role}:{subject}",
                    "role": role,
                    "expires_in": TOKEN_TTL_SECONDS,
                },
            )
            return

        self._json(404, {"error": "not found"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--port", type=int, default=5500, help="page port (default: 5500)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not settings.SIGNALING_JWT_SECRET:
        print("SIGNALING_JWT_SECRET is not set in .env - the signaling server would refuse every socket.")
        return 2

    smoke = _load_smoke_module()
    call_id, customer_id, employee_id = smoke.pick_interaction()

    Handler.call_id = call_id
    Handler.customer_id = customer_id
    Handler.employee_id = employee_id

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    base = f"http://127.0.0.1:{args.port}"

    print(f"""
WebRTC test harness
-------------------
signaling server : ws://127.0.0.1:8000/ws/signaling   (must be running)
interaction      : {call_id}
customer peer    : customer:{customer_id}
employee peer    : employee:{employee_id}

Open these two, one per tab:

  {base}/?role=customer
  {base}/?role=employee

In each tab: pick is prefilled, press Connect, allow the microphone.
The call connects automatically once both sides have joined - no second button.
Watch "Media stats": inbound audio bytes climbing means audio is really
flowing, not just SDP exchanged.

Ctrl-C to stop.
""")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
