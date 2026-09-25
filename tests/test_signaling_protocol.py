r"""
Signaling Module 1 (Protocol & Message Contract) — unit tests.

The protocol module is the contract every signaling participant builds
against, so these tests are deliberately strict about two things:

1. **The happy path is exact.** Every message type parses, and the envelope
   that comes back carries the field values the client sent.
2. **Every violation raises InvalidMessage.** Malformed JSON, a non-object
   frame, a missing field, an unknown ``type`` — all of them are the same
   exception type, never a raw ValueError/KeyError escaping to the caller
   that has to decide whether to close the socket.

Pure unit tests: no database, no network, no WebSocket.

Run from the backend project root:
    .\.venv\Scripts\python.exe -m pytest tests/test_signaling_protocol.py -q
"""

import json
import uuid
from datetime import datetime

import pytest

from app.signaling.exceptions import InvalidMessage, SignalingError
from app.signaling.models import MessageType, PeerRole, SignalingMessage
from app.signaling.protocol import (
    parse_message,
    serialize_message,
    validate_message,
    validate_payload,
)

CALL_ID = "3f1a7c22-0d5e-4b6a-9f21-6c0b7a8d1e33"
INTERACTION_ID = "3f1a7c22-0d5e-4b6a-9f21-6c0b7a8d1e33"

# The wire types fixed by Section 3.2 of the WebRTC doc. If this set ever
# changes, the Flutter and employee-web clients break — so it is asserted
# rather than trusted.
CONTRACT_TYPES = {
    "offer",
    "answer",
    "ice_candidate",
    "join",
    "ready",
    "call_state",
    "hangup",
    "error",
}


def valid_offer(**overrides) -> dict:
    """A minimal, contract-valid offer frame (overridable per test)."""
    frame = {
        "type": "offer",
        "call_id": CALL_ID,
        "interaction_id": INTERACTION_ID,
        "sender": "peer-customer",
        "target": "peer-employee",
        "payload": {"sdp": "v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\n"},
    }
    frame.update(overrides)
    return frame


# ---------------------------------------------------------------------------
# 1-3: the contract itself
# ---------------------------------------------------------------------------
def test_message_type_enum_matches_the_frozen_contract():
    """The eight wire types are the contract; adding one is a protocol change."""
    assert {member.value for member in MessageType} == CONTRACT_TYPES


def test_peer_role_enum_is_exactly_customer_and_employee():
    assert {member.value for member in PeerRole} == {"customer", "employee"}


@pytest.mark.parametrize("message_type", sorted(CONTRACT_TYPES))
def test_every_contract_message_type_parses(message_type):
    """Each of the eight types is accepted, not just the SDP-carrying ones."""
    message = validate_message(
        json.dumps(
            {
                "type": message_type,
                "call_id": CALL_ID,
                "payload": {"sdp": "v=0"} if message_type == "offer" else {},
            }
        )
    )

    assert message.type is MessageType(message_type)


# ---------------------------------------------------------------------------
# 4-7: the happy path returns a typed envelope with the client's values
# ---------------------------------------------------------------------------
def test_valid_offer_returns_a_typed_envelope():
    """The Module 1 acceptance criterion: valid offer JSON in, typed object out."""
    message = validate_message(json.dumps(valid_offer()))

    assert isinstance(message, SignalingMessage)
    assert message.type is MessageType.OFFER
    assert message.call_id == CALL_ID
    assert message.interaction_id == uuid.UUID(INTERACTION_ID)
    assert message.sender == "peer-customer"
    assert message.target == "peer-employee"
    assert message.payload == {"sdp": "v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\n"}


def test_offer_sdp_is_preserved_byte_for_byte():
    """SDP is forwarded verbatim — any rewriting would break the handshake."""
    sdp = "v=0\r\no=- 4611731400430051336 2 IN IP4 127.0.0.1\r\na=ice-ufrag:xY7/\r\n"

    message = validate_message(json.dumps(valid_offer(payload={"sdp": sdp})))

    assert message.payload["sdp"] == sdp


def test_optional_fields_may_be_omitted():
    """Only type and call_id are required; sender/target are filled by the server."""
    message = validate_message(
        json.dumps({"type": "ice_candidate", "call_id": CALL_ID, "payload": {}})
    )

    assert message.sender is None
    assert message.target is None
    assert message.interaction_id is None
    assert message.timestamp is None


def test_payload_defaults_to_empty_dict_and_is_not_shared():
    """Default payload must be per-instance, or one call would leak into another."""
    first = validate_message(json.dumps({"type": "hangup", "call_id": CALL_ID}))
    second = validate_message(json.dumps({"type": "hangup", "call_id": CALL_ID}))

    assert first.payload == {}

    first.payload["sdp"] = "leaked"

    assert second.payload == {}


def test_ice_candidate_payload_is_not_over_validated():
    """ICE shapes vary (candidate/sdpMid/sdpMLineIndex/usernameFragment); keep them free-form."""
    payload = {
        "candidate": "candidate:842163049 1 udp 1677729535 203.0.113.7 55011 typ srflx",
        "sdpMid": "0",
        "sdpMLineIndex": 0,
        "usernameFragment": "xY7/",
        "nested": {"ignored": [1, 2, {"deep": True}]},
    }

    message = validate_message(
        json.dumps({"type": "ice_candidate", "call_id": CALL_ID, "payload": payload})
    )

    assert message.payload == payload


def test_timestamp_is_parsed_as_a_datetime():
    message = validate_message(
        json.dumps(
            {
                "type": "call_state",
                "call_id": CALL_ID,
                "payload": {"state": "waiting"},
                "timestamp": "2026-09-25T18:00:00Z",
            }
        )
    )

    assert isinstance(message.timestamp, datetime)
    assert message.timestamp.year == 2026


def test_interaction_id_accepts_a_uuid_string():
    """Clients send UUIDs as text; the envelope normalises them to uuid.UUID."""
    message = validate_message(json.dumps(valid_offer()))

    assert message.interaction_id == uuid.UUID(INTERACTION_ID)


# ---------------------------------------------------------------------------
# 8-14: malformed input raises InvalidMessage, never anything else
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    [
        "{not json at all",
        "{'single': 'quotes'}",
        "",
        "   ",
    ],
)
def test_malformed_json_raises_invalid_message(raw):
    with pytest.raises(InvalidMessage):
        validate_message(raw)


@pytest.mark.parametrize("raw", ["null", "123", '"a string"', "[]", "[1, 2, 3]", "true"])
def test_json_that_is_not_an_object_raises_invalid_message(raw):
    """A frame must decode to a JSON object; arrays and scalars are contract violations."""
    with pytest.raises(InvalidMessage):
        validate_message(raw)


def test_unknown_type_value_raises_invalid_message():
    with pytest.raises(InvalidMessage):
        validate_message(json.dumps({"type": "telepathy", "call_id": CALL_ID}))


def test_non_string_type_raises_invalid_message():
    with pytest.raises(InvalidMessage):
        validate_message(json.dumps({"type": 7, "call_id": CALL_ID}))


def test_missing_type_raises_invalid_message():
    with pytest.raises(InvalidMessage):
        validate_message(json.dumps({"call_id": CALL_ID}))


def test_missing_call_id_raises_invalid_message():
    with pytest.raises(InvalidMessage):
        validate_message(json.dumps({"type": "offer", "payload": {}}))


def test_null_call_id_raises_invalid_message():
    with pytest.raises(InvalidMessage):
        validate_message(json.dumps({"type": "offer", "call_id": None}))


@pytest.mark.parametrize(
    "bad_interaction_id",
    ["not-a-uuid", "3f1a7c22", "", 42, {"id": "x"}],
)
def test_interaction_id_that_is_not_a_uuid_raises_invalid_message(bad_interaction_id):
    with pytest.raises(InvalidMessage):
        validate_message(
            json.dumps(
                {
                    "type": "offer",
                    "call_id": CALL_ID,
                    "interaction_id": bad_interaction_id,
                    "payload": {},
                }
            )
        )


@pytest.mark.parametrize("bad_payload", ["just a string", 5, ["a", "b"], True])
def test_payload_that_is_not_an_object_raises_invalid_message(bad_payload):
    with pytest.raises(InvalidMessage):
        validate_message(
            json.dumps({"type": "offer", "call_id": CALL_ID, "payload": bad_payload})
        )


def test_unparseable_timestamp_raises_invalid_message():
    with pytest.raises(InvalidMessage):
        validate_message(
            json.dumps({"type": "offer", "call_id": CALL_ID, "timestamp": "yesterday"})
        )


def test_none_and_non_text_input_raise_invalid_message():
    """Defensive: a caller that forwards a missing frame body still gets InvalidMessage."""
    for raw in (None, 5, {"already": "decoded"}, []):
        with pytest.raises(InvalidMessage):
            validate_message(raw)


# ---------------------------------------------------------------------------
# 15-18: parse_message — one entry point for every frame framing
# ---------------------------------------------------------------------------
def test_parse_message_accepts_raw_text():
    message = parse_message(json.dumps(valid_offer()))

    assert message.type is MessageType.OFFER


def test_parse_message_accepts_raw_utf8_bytes():
    message = parse_message(json.dumps(valid_offer()).encode("utf-8"))

    assert message.call_id == CALL_ID


def test_parse_message_accepts_an_already_decoded_dict():
    """receive_json() hands over a dict; it must not be re-parsed as text."""
    message = parse_message(valid_offer())

    assert message.sender == "peer-customer"
    assert isinstance(message, SignalingMessage)


@pytest.mark.parametrize("raw", [b"\xff\xfe\xfd", b"\x80\x81"])
def test_parse_message_rejects_non_utf8_bytes(raw):
    with pytest.raises(InvalidMessage):
        parse_message(raw)


@pytest.mark.parametrize("raw", ["nope", b"{oops", ["not", "a", "frame"], 12])
def test_parse_message_rejects_garbage_in_every_framing(raw):
    with pytest.raises(InvalidMessage):
        parse_message(raw)


# ---------------------------------------------------------------------------
# 19-21: errors carry the protocol code the endpoint reports to clients
# ---------------------------------------------------------------------------
def test_invalid_message_is_a_signaling_error_with_its_own_code():
    """The endpoint converts these to an error envelope; one code, one type."""
    with pytest.raises(InvalidMessage) as excinfo:
        validate_message("{broken")

    assert isinstance(excinfo.value, SignalingError)
    assert excinfo.value.code == "INVALID_MESSAGE"


def test_validation_failure_states_which_rule_was_broken():
    """A bare 'invalid message' is unactionable for the client teams."""
    with pytest.raises(InvalidMessage) as excinfo:
        validate_message(json.dumps({"type": "offer", "call_id": CALL_ID, "payload": 1}))

    assert "schema validation" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# 22-24: serialization / round trip
# ---------------------------------------------------------------------------
def test_serialize_message_round_trips_through_parse_message():
    original = validate_message(json.dumps(valid_offer()))

    reparsed = parse_message(serialize_message(original))

    assert reparsed == original


def test_serialize_message_omits_absent_optional_fields():
    """Unset fields are dropped so the wire frame stays minimal, not null-filled."""
    message = SignalingMessage(type=MessageType.HANGUP, call_id=CALL_ID)

    raw = serialize_message(message)
    wire = json.loads(raw)

    assert "sender" not in wire
    assert "target" not in wire
    assert "interaction_id" not in wire
    assert "timestamp" not in wire
    assert wire == {"type": "hangup", "call_id": CALL_ID, "payload": {}}


def test_serialized_message_is_valid_json_text():
    raw = serialize_message(validate_message(json.dumps(valid_offer())))

    assert isinstance(raw, str)

    parsed = json.loads(raw)

    assert parsed["type"] == "offer"
    assert parsed["payload"]["sdp"].startswith("v=0")


# ---------------------------------------------------------------------------
# 25-26: validate_payload — the mapping-level entry point
# ---------------------------------------------------------------------------
def test_validate_payload_accepts_a_mapping():
    message = validate_payload(valid_offer())

    assert message.type is MessageType.OFFER


@pytest.mark.parametrize("data", [None, "text", 3, ["list"], True])
def test_validate_payload_rejects_non_mappings(data):
    with pytest.raises(InvalidMessage):
        validate_payload(data)
