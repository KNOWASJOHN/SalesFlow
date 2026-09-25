"""
Signaling Module 4: room ownership checks.

Module 3's SignalingManager is database-free by design — it only knows how to
route between the two sockets already in a room. Something therefore has to
answer a different question *before* a peer is allowed into a room:

    is this authenticated principal actually a party to the interaction that
    this call is about?

Without that check, any authenticated user could join any ``call_id`` they
could guess and would then be routed each other peer's SDP and ICE payloads.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.auth import AuthPrincipal
from app.models.interaction import Interaction
from app.models.journey import Journey
from app.signaling.exceptions import SignalingError

# The role string that means "the customer on this journey".
CUSTOMER_ROLE = "customer"

# Wire code reported to the client when ownership cannot be proven.
AUTH_FAILED = "AUTH_FAILED"

# One message for every failure: "not found" and "not yours" must be
# indistinguishable, otherwise the endpoint becomes an oracle for probing which
# interaction ids exist.
ACCESS_DENIED_MESSAGE = "The authenticated peer cannot access this interaction."


def authorize_interaction_access(
    db: Session,
    principal: AuthPrincipal,
    interaction_id: uuid.UUID,
) -> Interaction:
    """
    Return the Interaction when ``principal`` is a party to it.

    A customer is a party when they own the journey the interaction belongs to;
    an employee is a party when they are the interaction's assigned employee.

    Raises:
        SignalingError: with code ``AUTH_FAILED`` when the interaction does not
            exist, when it belongs to somebody else, or when its journey is
            missing.
    """
    row = (
        db.query(Interaction, Journey.customer_id)
        .join(Journey, Interaction.journey_id == Journey.journey_id)
        .filter(Interaction.interaction_id == interaction_id)
        .first()
    )

    if row is None:
        raise SignalingError(ACCESS_DENIED_MESSAGE, code=AUTH_FAILED)

    interaction, journey_customer_id = row

    if principal.role == CUSTOMER_ROLE:
        allowed = journey_customer_id is not None and journey_customer_id == principal.subject
    else:
        allowed = interaction.employee_id == principal.subject

    if not allowed:
        raise SignalingError(ACCESS_DENIED_MESSAGE, code=AUTH_FAILED)

    return interaction
