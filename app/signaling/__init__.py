"""
WebRTC signaling package.

Modules implemented so far (per the WebRTC Signaling Build Plan):
    1. Protocol & Message Contract -> models.py, protocol.py, exceptions.py
    2. Room & Peer Registry        -> room.py
    3. Signaling Manager           -> manager.py

Everything here is transport-agnostic, in-memory state. Nothing in this package
touches PostgreSQL, and no audio/media ever passes through it.
"""

from app.signaling.exceptions import (
    InvalidMessage,
    PeerNotConnected,
    RoomFull,
    RoomNotFound,
    SignalingError,
    UnauthorizedPeer,
)
from app.signaling.manager import SignalingManager
from app.signaling.models import JoinPayload, MessageType, PeerRole, SignalingMessage
from app.signaling.protocol import parse_message, serialize_message, validate_message
from app.signaling.room import Peer, Room

__all__ = [
    "InvalidMessage",
    "JoinPayload",
    "MessageType",
    "Peer",
    "PeerNotConnected",
    "PeerRole",
    "Room",
    "RoomFull",
    "RoomNotFound",
    "SignalingError",
    "SignalingManager",
    "SignalingMessage",
    "UnauthorizedPeer",
    "parse_message",
    "serialize_message",
    "validate_message",
]
