# Signaling contract (WebRTC connection setup)

Frozen at backend Signaling Module 6. This is what the employee web client and
the Flutter client build against.

The signaling server carries **connection setup only** — SDP offers/answers and
ICE candidates. No audio ever passes through it. Once the two clients have
exchanged those messages they talk to each other directly.

- Endpoint: `ws://<host>/ws/signaling?access_token=<jwt>`
- One socket = one participant in one call.
- Each call has exactly one `customer` and one `employee`.

---

## 1. Connecting

Browsers cannot set an `Authorization` header on a WebSocket upgrade, so the
token goes in the query string. It is an HS256 JWT with these claims:

| Claim | Required | Value |
|---|---|---|
| `sub` | yes | your `customer_id` or `employee_id`, as a UUID |
| `role` | yes | `"customer"` or `"employee"` |
| `aud` | yes (verified) | `"sales-signaling"` |
| `exp` | yes | expiry, unix seconds |

Signed with the shared secret in `SIGNALING_JWT_SECRET` on the server side.
Any standard HS256 JWT library mints it — `jsonwebtoken` in the web client,
`dart_jsonwebtoken` in Flutter, `PyJWT` in Python.

The token is the only trusted statement of identity. Whatever you put in a
message's `sender` field is discarded and replaced by the server.

If the token is missing, badly signed, expired, has the wrong audience, or
carries a role other than `customer`/`employee`, the server sends one error
frame and closes the socket with code **1008**.

---

## 2. Message envelope

Every message in both directions is one JSON object:

```json
{
  "type": "offer",
  "call_id": "3f1a7c22-0d5e-4b6a-9f21-6c0b7a8d1e33",
  "interaction_id": "3f1a7c22-0d5e-4b6a-9f21-6c0b7a8d1e33",
  "sender": "customer:6f9c1b40-...",
  "target": "employee:8a2d5e77-...",
  "payload": { "sdp": "v=0\r\no=- 4611731400430051336 2 IN IP4 127.0.0.1\r\n" },
  "timestamp": "2026-09-25T18:00:00Z"
}
```

| Field | Required | Notes |
|---|---|---|
| `type` | yes | one of the eight values below |
| `call_id` | yes | the interaction UUID for this call |
| `interaction_id` | no | if you send it, it must equal `call_id` |
| `sender` | no | ignored on the way in; overwritten on the way out |
| `target` | no | optional explicit recipient; if sent it must be the other participant of this call |
| `payload` | no | free-form object; defaults to `{}`. SDP/ICE shapes are not validated |
| `timestamp` | no | accepted but never set or used by the server — do not rely on it |

The room key is the canonical lowercase, hyphenated form of `call_id`, so two
clients that spell the same UUID differently still meet in the same room.

### The eight types

| Type | Direction | Meaning |
|---|---|---|
| `join` | client → server | first frame on the socket, claims a role |
| `ready` | server → client | both participants present, safe to create the offer |
| `offer` | client ↔ client | SDP offer, forwarded verbatim |
| `answer` | client ↔ client | SDP answer, forwarded verbatim |
| `ice_candidate` | client ↔ client | one ICE candidate, forwarded verbatim |
| `hangup` | client → server | ends the call |
| `call_state` | server → client | call lifecycle notice |
| `error` | server → client | a problem with your frame |

A client may **send** only `join`, `offer`, `answer`, `ice_candidate` and
`hangup`. Sending `ready`, `call_state` or `error` gets an `INVALID_MESSAGE`
error — a client cannot fake server-side state.

---

## 3. Call flow

```
customer socket                     server                     employee socket
─────────────────────────────────────────────────────────────────────────────
join {role: customer}  ─────────►
                       ◄───────────  call_state {state: waiting}
                                                ◄───────────── join {role: employee}
                       ◄───────────  ready {state: ready}  ─────────►  (both peers)
offer (sdp)            ─────────►    ·forwarded verbatim·  ─────────►
                       ◄───────────  answer (sdp)          ◄─────────────
ice_candidate          ─────────►    ·forwarded verbatim·  ─────────►
                       ◄───────────  ice_candidate         ◄─────────────
hangup                 ─────────►  ·room torn down·
                                                ◄──── call_state {state: ended}
  (or socket dies)     ─────────►  ·peer removed·
                                                ◄──── call_state {state: peer_left}
```

Either side may create the offer; the server does not care which one goes
first. Both peers receive `ready` the moment the second one joins.

`join` payload:

```json
{ "type": "join", "call_id": "<interaction uuid>", "payload": { "role": "customer" } }
```

The role you claim must match the `role` claim in your token, and the
interaction must belong to you:

- a **customer** must own the journey the interaction belongs to
- an **employee** must be the interaction's assigned employee

Any failure here is reported as `AUTH_FAILED` and the socket is closed with
1008. "Does not exist" and "belongs to someone else" are deliberately
indistinguishable, so the endpoint cannot be used to probe which interaction
IDs exist.

---

## 4. Ending a call

- **Explicit:** send `hangup`. The room is torn down and the other participant
  receives `call_state {"state": "ended"}`.
- **Abrupt:** close the socket, kill the tab, lose the network. The server
  removes you from the room and pushes the surviving participant
  `call_state {"state": "peer_left"}`.

So a client does not have to send a frame into the void to discover the other
side is gone. Use the two states differently:

| Received | Meaning | Suggested reaction |
|---|---|---|
| `{"state": "ended"}` | the other side hung up deliberately | close the call UI |
| `{"state": "peer_left"}` | the other socket dropped without a hangup | offer a reconnect or end the call |

`peer_left` means the peer's *socket* died — it may reconnect to the same
`call_id`, in which case the server treats it as a fresh join. A stale
`PEER_NOT_CONNECTED` on a frame sent before the notice arrived is still
possible; treat the two as the same outcome.

---

## 5. Error frames

```json
{ "type": "error", "payload": { "code": "PEER_NOT_CONNECTED", "message": "..." } }
```

Error frames carry **no** `call_id`. Match them to your open socket.

| Code | When | Socket after |
|---|---|---|
| `INVALID_MESSAGE` | not JSON, not an object, missing `type`/`call_id`, unknown `type`, malformed `join` payload, `call_id` not a UUID, `call_id` ≠ `interaction_id` | stays open (closes 1008 if pre-join) |
| `AUTH_FAILED` | bad/expired/missing token, unconfigured server secret, claimed role ≠ token role, interaction not yours | 1008, closed |
| `ROOM_FULL` | that role's slot in the call is already taken | 1008, closed |
| `ROOM_NOT_FOUND` | the call was already torn down | stays open |
| `PEER_NOT_CONNECTED` | no other participant yet, or `target` is not this call's other participant | stays open |

Pre-join failures and authentication failures close the socket with code 1008
(policy violation) — the numeric close frame cannot carry a reason, which is
why an error frame is always sent first. Mid-call errors do not close the
socket; you may keep the call going.

---

## 6. Client rules of thumb

1. Connect, then send `join` as your very first frame. Anything else closes the
   socket.
2. Wait for `ready` before creating the offer if you want to be sure the other
   side is listening — though a message sent into an empty room is a no-op
   rather than an error, so an early offer is not fatal.
3. Never trust `sender` on an incoming frame to be un-spoofed by the other
   client: it *is* server-stamped, and it is the other participant.
4. Ignore `timestamp`.
5. Keep `payload` shapes for SDP/ICE exactly as your WebRTC library produces
   them. The server forwards them verbatim and never inspects them.
6. Do not retry a closed socket with the same token if the code was 1008 —
   the failure is in the identity or the ownership, not in the transport.
