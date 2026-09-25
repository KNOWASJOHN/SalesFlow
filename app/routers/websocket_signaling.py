"""
Signaling Module 4: the ``/ws/signaling`` WebSocket endpoint.

This router is the only bridge between the raw WebSocket transport and Module
3's SignalingManager. For every frame it answers four questions and nothing
else:

1. **Who is this?**  The ``access_token`` query parameter is verified; the
   resulting :class:`~app.core.auth.AuthPrincipal` is the only trusted identity
   on the socket. Anything a client puts in a message's ``sender`` field is
   discarded.
2. **May they be here?**  :func:`~app.signaling.authorization.authorize_interaction_access`
   proves the interaction belongs to that principal.
3. **What did they send?**  :func:`~app.signaling.protocol.parse_message`
   enforces the Module 1 contract.
4. **Where does it go?**  The SignalingManager routes to the opposite peer of
   the *same* call only — SDP and ICE payloads are forwarded verbatim and never
   inspected or persisted.

Message flow
------------
``connect``   -> accept, then verify the token (fatal on failure: error frame
                 followed by close 1008).
``join``      -> first frame must be a join; its claimed role must equal the
                 token's role, and the interaction must belong to the caller.
                 The first peer in an empty room gets ``call_state``
                 ``{"state": "waiting"}``; the join that completes the pair
                 makes the server send ``ready`` to both peers.
``offer`` / ``answer`` / ``ice_candidate``
              -> routed verbatim to the opposite peer, with ``sender`` stamped
                 by the server and ``target`` resolved by the server.
``hangup``    -> the opposite peer receives ``call_state`` ``{"state": "ended"}``
                 and the room is torn down.
``disconnect``-> the peer is removed from the room and the opposite peer
                 receives ``call_state`` ``{"state": "peer_left"}``, so a client
                 can react to a dropped peer without having to send a frame
                 into the void first. A later send from that survivor still
                 gets ``PEER_NOT_CONNECTED``, which remains the authoritative
                 answer if the notice was missed.

Every failure is reported with the Module 1 error envelope,
``{"type": "error", "payload": {"code": ..., "message": ...}}``.
"""

import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, WebSocket
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.core.auth import AuthPrincipal, AuthenticationError, get_token_verifier
from app.core.database import get_db
from app.signaling.authorization import authorize_interaction_access
from app.signaling.exceptions import (
    InvalidMessage,
    PeerNotConnected,
    RoomNotFound,
    SignalingError,
)
from app.signaling.manager import SignalingManager
from app.signaling.models import JoinPayload, MessageType, PeerRole, SignalingMessage
from app.signaling.protocol import parse_message, serialize_message

logger = logging.getLogger(__name__)

router = APIRouter(tags=["signaling"])

# Process-wide room registry. Signaling state is deliberately ephemeral
# (Module 3): a restart drops every call, which is correct for live media.
signaling_manager = SignalingManager()

# Frame types a peer may send once it has joined.
ROUTABLE_TYPES = frozenset(
    {
        MessageType.OFFER,
        MessageType.ANSWER,
        MessageType.ICE_CANDIDATE,
        MessageType.HANGUP,
    }
)

# Wire codes that are not 1:1 with a SignalingError subclass.
AUTH_FAILED = "AUTH_FAILED"

# RFC 6455 close code 1008 = policy violation (authentication/handshake failure).
POLICY_VIOLATION = 1008

# `call_state` payload states emitted by this endpoint.
STATE_WAITING = "waiting"
STATE_ENDED = "ended"


# ---------------------------------------------------------------------------
# Outbound helpers
# ---------------------------------------------------------------------------
async def _send_event(websocket: WebSocket, message: SignalingMessage) -> None:
    """Send a SignalingMessage using the wire format owned by Module 1."""
    await websocket.send_text(serialize_message(message))


async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
    """Send the Module 1 error envelope: ``{"type": "error", "payload": {...}}``."""
    await websocket.send_text(
        json.dumps(
            {
                "type": MessageType.ERROR.value,
                "payload": {"code": code, "message": message},
            }
        )
    )


async def _send_call_state(websocket: WebSocket, call_id: str, state: str) -> None:
    """Tell one peer how the call is doing (waiting / ended)."""
    await _send_event(
        websocket,
        SignalingMessage(
            type=MessageType.CALL_STATE,
            call_id=call_id,
            sender="server",
            payload={"state": state},
        ),
    )


async def _send_ready(call_id: str) -> None:
    """
    Announce that both participants are present.

    Sent to *both* peers the moment the second one joins, which is the only
    thing clients need before the caller creates its offer.
    """
    room = signaling_manager.rooms.get(call_id)

    if room is None:  # pragma: no cover - the room was registered a line earlier
        return

    for peer in (room.customer_peer, room.employee_peer):
        if peer is not None:
            await _send_event(
                peer.websocket,
                SignalingMessage(
                    type=MessageType.READY,
                    call_id=call_id,
                    sender="server",
                    payload={"state": "ready"},
                ),
            )


# ---------------------------------------------------------------------------
# Inbound helpers
# ---------------------------------------------------------------------------
def _frame_payload(frame: dict) -> Any:
    """Pull the text (or binary) body out of a raw ASGI websocket message."""
    text = frame.get("text")

    if text is not None:
        return text

    return frame.get("bytes")


def _resolve_call_id(message: SignalingMessage) -> str:
    """
    Work out which room a ``join`` belongs to, and authorise against what.

    ``call_id`` is the in-memory room key and ``interaction_id`` is the database
    row the call is about. They denote the same interaction, so a client that
    sends both must send consistent values rather than have the server guess.
    The canonical (lowercase, hyphenated) form is used as the room key so two
    peers that spell the same UUID differently still meet in one room.
    """
    if message.interaction_id is not None and str(message.interaction_id) != message.call_id:
        raise InvalidMessage("call_id and interaction_id must refer to the same interaction.")

    try:
        return str(uuid.UUID(message.call_id))
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidMessage("call_id must be the interaction UUID for the call.") from exc


def _validate_join(message: SignalingMessage, principal: AuthPrincipal) -> tuple[str, PeerRole]:
    """
    Validate the opening frame and return ``(call_id, role)``.

    Raises:
        InvalidMessage: the join payload is malformed, or the call id is not a
            UUID.
        SignalingError: with code ``AUTH_FAILED`` when the claimed role is not
            the role the token was issued for.
    """
    try:
        payload = JoinPayload.model_validate(message.payload)
    except ValidationError as exc:
        raise InvalidMessage(f"Join payload failed schema validation: {exc}") from exc

    if payload.role.value != principal.role:
        raise SignalingError(
            "The joined role does not match the role of the access token.",
            code=AUTH_FAILED,
        )

    return _resolve_call_id(message), payload.role


async def _route(message: SignalingMessage, call_id: str, peer_id: str) -> None:
    """
    Forward one post-join frame to the opposite peer of the same call.

    The envelope is rewritten before it leaves: ``sender`` becomes the
    authenticated peer id (a client's claim about its own identity is never
    trusted), ``call_id``/``interaction_id`` become the room's own values, and
    ``target`` is resolved to the real opposite peer.

    Raises:
        RoomNotFound: the call has already been torn down.
        PeerNotConnected: there is no opposite peer, or ``target`` names
            somebody who is not the opposite peer of this call.
    """
    room = signaling_manager.rooms.get(call_id)

    if room is None:
        raise RoomNotFound(f"The call {call_id} is no longer active.")

    other_peer = room.get_other_peer(peer_id)

    if other_peer is None:
        raise PeerNotConnected("The other participant is not connected to this call.")

    if message.target is not None and message.target != other_peer.peer_id:
        raise PeerNotConnected("target is not the other participant of this call.")

    await signaling_manager.send_to_peer(
        call_id,
        peer_id,
        message.model_copy(
            update={
                "call_id": call_id,
                "interaction_id": uuid.UUID(call_id),
                "sender": peer_id,
                "target": other_peer.peer_id,
            }
        ),
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@router.websocket("/ws/signaling")
async def signaling_endpoint(
    websocket: WebSocket,
    access_token: Optional[str] = Query(
        default=None,
        description="HS256 JWT identifying the peer (sub + role claims).",
    ),
    db: Session = Depends(get_db),
) -> None:
    """
    Authenticated signaling socket: one socket == one call participant.

    The socket is accepted before the token is checked because a WebSocket close
    frame can only carry a numeric code — the reason has to be delivered as an
    application-level error message first.
    """
    await websocket.accept()

    try:
        principal = get_token_verifier().verify(access_token or "")
    except AuthenticationError as exc:
        await _send_error(websocket, AUTH_FAILED, str(exc))
        await websocket.close(code=POLICY_VIOLATION)
        return

    peer_id = principal.peer_id
    call_id: Optional[str] = None
    joined = False

    try:
        # ---- 1. the first frame must be a join -----------------------------
        frame = await websocket.receive()

        if frame["type"] == "websocket.disconnect":
            return

        try:
            join = parse_message(_frame_payload(frame))
        except InvalidMessage as exc:
            await _send_error(websocket, exc.code, exc.message)
            await websocket.close(code=POLICY_VIOLATION)
            return

        if join.type is not MessageType.JOIN:
            await _send_error(
                websocket,
                InvalidMessage.code,
                "The first message on a signaling socket must be a join.",
            )
            await websocket.close(code=POLICY_VIOLATION)
            return

        # ---- 2. role + ownership, then register the room -------------------
        try:
            call_id, role = _validate_join(join, principal)
            authorize_interaction_access(db, principal, uuid.UUID(call_id))
            room = await signaling_manager.register_peer(call_id, peer_id, role, websocket)
        except SignalingError as exc:
            await _send_error(websocket, exc.code, exc.message)
            await websocket.close(code=POLICY_VIOLATION)
            return

        joined = True
        logger.info("signaling: %s joined call %s", peer_id, call_id)

        # ---- 3. announce where the call stands -----------------------------
        if room.is_ready():
            await _send_ready(call_id)
        else:
            await _send_call_state(websocket, call_id, STATE_WAITING)


        # ---- 4. route frames between the two peers -------------------------
        while True:
            frame = await websocket.receive()

            if frame["type"] == "websocket.disconnect":
                break

            try:
                message = parse_message(_frame_payload(frame))
            except InvalidMessage as exc:
                await _send_error(websocket, exc.code, exc.message)
                continue

            if message.type is MessageType.JOIN:
                await _send_error(
                    websocket,
                    InvalidMessage.code,
                    "This socket has already joined the call.",
                )
                continue

            if message.type not in ROUTABLE_TYPES:
                await _send_error(
                    websocket,
                    InvalidMessage.code,
                    f"Message type '{message.type.value}' is not valid after join.",
                )
                continue

            if message.type is MessageType.HANGUP:
                # Hangup is the explicit end-of-call signal. Drop this peer
                # first so the "ended" notice reaches the *other* participant,
                # then tear the room down and stop reading.
                await signaling_manager.remove_peer(call_id, peer_id)
                await signaling_manager.close_room(call_id)
                break

            try:
                await _route(message, call_id, peer_id)
            except SignalingError as exc:
                await _send_error(websocket, exc.code, exc.message)
                continue
    except WebSocketDisconnect:
        # The ordinary teardown path: the client went away.
        pass
    except Exception:  # pragma: no cover - defensive: one broken socket must
        # never take the process, or the other peer's call, down with it.
        logger.exception("signaling: unexpected failure for peer %s", peer_id)
        try:
            await _send_error(websocket, "SERVER_ERROR", "Signaling failed unexpectedly.")
        except Exception:
            pass
    finally:
        if joined and call_id is not None:
            # Tell the survivor before dropping the leaver: a socket that went
            # away without a hangup would otherwise leave the other client
            # waiting on a peer that is never coming back.
            await signaling_manager.notify_peer_left(call_id, peer_id)
            await signaling_manager.remove_peer(call_id, peer_id)
            logger.info("signaling: %s left call %s", peer_id, call_id)
