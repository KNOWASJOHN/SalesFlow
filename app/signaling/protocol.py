import json
from typing import Any
from pydantic import ValidationError

from app.signaling.models import SignalingMessage
from app.signaling.exceptions import InvalidMessage


def validate_message(raw: str) -> SignalingMessage:
    """
    Parse and validate a raw text frame received over the WebSocket into a
    typed SignalingMessage. Raises InvalidMessage for anything that doesn't
    conform to the protocol contract — malformed JSON, missing required
    fields, or an unrecognized `type`.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InvalidMessage(f"Message is not valid JSON: {exc}") from exc

    return validate_payload(data)


def validate_payload(data: Any) -> SignalingMessage:
    """
    Validate an already-decoded frame (a dict) into a typed SignalingMessage.

    Split out from ``validate_message`` so the same strictness applies whether
    the caller hands over raw text or a mapping — the WebSocket endpoint reads
    frames with ``receive_json``, which has already decoded them.
    """
    if not isinstance(data, dict):
        raise InvalidMessage("Message must be a JSON object.")

    try:
        return SignalingMessage.model_validate(data)
    except ValidationError as exc:
        raise InvalidMessage(f"Message failed schema validation: {exc}") from exc


def parse_message(data: Any) -> SignalingMessage:
    """
    Validate a client frame that may arrive as decoded JSON (dict), raw text
    (str), or raw bytes. Raises InvalidMessage on any protocol violation, so
    callers can rely on a single error type whatever the frame framing was.
    """
    if isinstance(data, (bytes, bytearray)):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidMessage(f"Message is not valid UTF-8: {exc}") from exc

    if isinstance(data, str):
        return validate_message(data)

    return validate_payload(data)


def serialize_message(message: SignalingMessage) -> str:
    """Serialize a SignalingMessage back to a JSON string for sending over the wire."""
    return message.model_dump_json(exclude_none=True)