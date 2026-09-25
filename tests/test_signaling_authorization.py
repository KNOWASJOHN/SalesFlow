"""
Signaling Module 4 - interaction ownership tests.

``authorize_interaction_access`` is the security boundary of the signaling
socket: it is what stops an authenticated customer from joining somebody else's
call (or an employee from joining a call they are not handling). The endpoint
tests stub this function out, so it is covered here directly with a fake session
- no PostgreSQL, no network.

The fake session only has to survive the one chained query the function makes:
``session.query(...).join(...).filter(...).first()``.

Run from the backend project root:
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_signaling_authorization.py -q
"""

import uuid
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from app.core.auth import AuthPrincipal
from app.signaling.authorization import (
    AUTH_FAILED,
    ACCESS_DENIED_MESSAGE,
    authorize_interaction_access,
)
from app.signaling.exceptions import SignalingError


class FakeQuery:
    """Chainable stand-in for a SQLAlchemy Query that always returns one row."""

    def __init__(self, row: Optional[tuple]):
        self.row = row

    def join(self, *args: Any, **kwargs: Any) -> "FakeQuery":
        return self

    def filter(self, *args: Any, **kwargs: Any) -> "FakeQuery":
        return self

    def first(self):
        return self.row


class FakeSession:
    """Records the entities it was asked for and replays a canned row."""

    def __init__(self, row: Optional[tuple]):
        self.row = row
        self.queried: list[tuple] = []

    def query(self, *entities: Any) -> FakeQuery:
        self.queried.append(entities)
        return FakeQuery(self.row)


CUSTOMER_ID = uuid.uuid4()
OTHER_CUSTOMER_ID = uuid.uuid4()
EMPLOYEE_ID = uuid.uuid4()
OTHER_EMPLOYEE_ID = uuid.uuid4()
INTERACTION_ID = uuid.uuid4()


def interaction(employee_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(interaction_id=INTERACTION_ID, employee_id=employee_id)


def session_for(employee_id: uuid.UUID, customer_id: uuid.UUID) -> FakeSession:
    """A session whose single row is (interaction, journey.customer_id)."""
    return FakeSession((interaction(employee_id), customer_id))


def principal(role: str, subject: uuid.UUID) -> AuthPrincipal:
    return AuthPrincipal(subject=subject, role=role)


def test_customer_who_owns_the_journey_may_join():
    db = session_for(EMPLOYEE_ID, customer_id=CUSTOMER_ID)

    result = authorize_interaction_access(
        db, principal("customer", CUSTOMER_ID), INTERACTION_ID
    )

    assert result.interaction_id == INTERACTION_ID
    # Ownership has to come from the journey, not from the interaction row.
    entities = db.queried[0]
    assert entities[1].key == "customer_id"


def test_customer_who_does_not_own_the_journey_is_refused():
    db = session_for(EMPLOYEE_ID, customer_id=OTHER_CUSTOMER_ID)

    with pytest.raises(SignalingError) as excinfo:
        authorize_interaction_access(db, principal("customer", CUSTOMER_ID), INTERACTION_ID)

    assert excinfo.value.code == AUTH_FAILED


def test_employee_assigned_to_the_interaction_may_join():
    db = session_for(EMPLOYEE_ID, customer_id=CUSTOMER_ID)

    result = authorize_interaction_access(
        db, principal("employee", EMPLOYEE_ID), INTERACTION_ID
    )

    assert result.employee_id == EMPLOYEE_ID


def test_employee_who_does_not_handle_the_interaction_is_refused():
    """Being on the journey is not enough for an employee - only their own row is."""
    db = session_for(OTHER_EMPLOYEE_ID, customer_id=CUSTOMER_ID)

    with pytest.raises(SignalingError) as excinfo:
        authorize_interaction_access(db, principal("employee", EMPLOYEE_ID), INTERACTION_ID)

    assert excinfo.value.code == AUTH_FAILED


def test_unknown_interaction_is_refused():
    db = FakeSession(None)

    with pytest.raises(SignalingError) as excinfo:
        authorize_interaction_access(db, principal("customer", CUSTOMER_ID), INTERACTION_ID)

    assert excinfo.value.code == AUTH_FAILED


def test_interaction_without_a_journey_customer_is_refused():
    """Defensive: a NULL customer_id must deny, never match by accident."""
    db = session_for(EMPLOYEE_ID, customer_id=None)

    with pytest.raises(SignalingError) as excinfo:
        authorize_interaction_access(db, principal("customer", CUSTOMER_ID), INTERACTION_ID)

    assert excinfo.value.code == AUTH_FAILED


def test_missing_interaction_and_foreign_interaction_are_indistinguishable():
    """
    The endpoint must not become an oracle: a caller who cannot access an
    interaction learns the same thing whether or not it exists.
    """
    missing = FakeSession(None)
    foreign = session_for(EMPLOYEE_ID, customer_id=OTHER_CUSTOMER_ID)
    customer = principal("customer", CUSTOMER_ID)

    with pytest.raises(SignalingError) as missing_error:
        authorize_interaction_access(missing, customer, INTERACTION_ID)

    with pytest.raises(SignalingError) as foreign_error:
        authorize_interaction_access(foreign, customer, INTERACTION_ID)

    assert missing_error.value.code == foreign_error.value.code == AUTH_FAILED
    assert missing_error.value.message == foreign_error.value.message == ACCESS_DENIED_MESSAGE
