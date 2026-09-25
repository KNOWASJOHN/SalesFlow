"""
Signaling authentication (Module 4).

The /ws/signaling handshake carries an ``access_token`` query parameter because
browsers cannot set an Authorization header on a WebSocket upgrade (the token
is scrubbed from access logs by app/core/logging.py).

The token is an ordinary HS256 JWT signed with ``SIGNALING_JWT_SECRET``:

    {"sub": "<customer_id|employee_id>", "role": "customer|employee",
     "aud": "sales-signaling", "exp": <unix timestamp>}

The principal returned by :meth:`HS256TokenVerifier.verify` is the *only*
trusted statement of who is on the other end of the socket. Everything a client
puts in the ``sender`` field of a signaling message is ignored and overwritten
by the endpoint.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol

import jwt
from jwt import InvalidTokenError

from app.core.config import settings

# Only call participants may open a signaling socket.
SIGNALING_ROLES = frozenset({"customer", "employee"})


class AuthenticationError(Exception):
    """Raised when a signaling token cannot be used to establish an identity."""


@dataclass(frozen=True)
class AuthPrincipal:
    """The authenticated identity behind one signaling socket."""

    subject: uuid.UUID
    role: str

    @property
    def peer_id(self) -> str:
        """
        The peer identifier used inside a signaling room.

        Namespacing by role keeps the two sides of a call from colliding when a
        customer and an employee happen to share the same UUID.
        """
        return f"{self.role}:{self.subject}"


class TokenVerifier(Protocol):
    """Verifies a raw signaling token and returns the authenticated principal."""

    def verify(self, token: str) -> AuthPrincipal:
        ...  # pragma: no cover - protocol declaration


class HS256TokenVerifier:
    """
    Verifies HS256 signaling JWTs and returns the authenticated principal.

    Verification is deliberately strict: algorithm, signature, ``exp``,
    ``aud`` and the required ``sub``/``role`` claims must all hold, and the
    subject must parse as a UUID so it can be compared against database keys.
    """

    def __init__(
        self,
        secret: str,
        algorithm: str = "HS256",
        audience: str = "sales-signaling",
    ):
        self.secret = secret
        self.algorithm = algorithm
        self.audience = audience

    def verify(self, token: str) -> AuthPrincipal:
        """
        Return the principal encoded in ``token``.

        Raises:
            AuthenticationError: for a missing token, a bad signature, an
                expired token, a wrong audience, malformed claims, or a role
                that is not allowed to use signaling.
        """
        if not token:
            raise AuthenticationError("A signaling access token is required.")

        try:
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=[self.algorithm],
                audience=self.audience,
                options={"require": ["sub", "role", "exp"]},
            )
        except InvalidTokenError as exc:
            # Deliberately vague: never leak *why* a token was rejected.
            raise AuthenticationError("Invalid or expired signaling token.") from exc

        try:
            subject = uuid.UUID(str(claims["sub"]))
            role = str(claims["role"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError("Invalid or expired signaling token.") from exc

        if role not in SIGNALING_ROLES:
            raise AuthenticationError("Token role is not allowed to use signaling.")

        return AuthPrincipal(subject=subject, role=role)


def get_token_verifier() -> TokenVerifier:
    """
    Build the token verifier from settings.

    A factory rather than a module-level singleton so tests and future
    deployments can rotate ``SIGNALING_JWT_SECRET`` without re-importing, and
    so an unconfigured app fails closed at socket time instead of at import.
    """
    secret = settings.SIGNALING_JWT_SECRET

    if not secret:
        raise AuthenticationError("Signaling token verification is not configured.")

    return HS256TokenVerifier(
        secret=secret,
        algorithm=settings.SIGNALING_JWT_ALGORITHM,
        audience=settings.SIGNALING_JWT_AUDIENCE,
    )
