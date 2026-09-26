"""
Feedback attribution and reads.

Attribution is denormalised onto the feedback row at write time: the employee
and department a journey actually ended with are copied onto the feedback
record, so "feedback for this employee" is a plain column filter instead of a
join chain through journeys and interactions on every read.

The feedback table already carried ``employee_id`` and ``department_id``; what
was missing was anyone filling them in. This module is that write-side resolver
plus the read side that uses the result.
"""

import uuid
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.pagination import PageParams
from app.models.feedback import Feedback
from app.models.interaction import Interaction


def resolve_attribution(
    db: Session,
    journey_id: uuid.UUID,
) -> Tuple[Optional[uuid.UUID], Optional[uuid.UUID]]:
    """
    Return the ``(employee_id, department_id)`` a journey's feedback belongs to.

    The interaction with the highest ``interaction_order`` is the one the
    journey ended on. After a transfer that is the receiving employee in the
    receiving department — which is what a customer rating is really about.
    Attributing to the first interaction instead would credit the employee who
    handed the customer on, the classic way this goes wrong.

    Returns ``(None, None)`` for a journey with no interactions at all: such
    feedback is genuine but unattributable, and a nullable column says that
    honestly rather than inventing an owner.
    """
    latest = (
        db.query(Interaction)
        .filter(Interaction.journey_id == journey_id)
        .order_by(Interaction.interaction_order.desc())
        .first()
    )

    if latest is None:
        return None, None

    return latest.employee_id, latest.department_id


def list_feedback(
    db: Session,
    employee_id: Optional[uuid.UUID] = None,
    department_id: Optional[uuid.UUID] = None,
    page: Optional[PageParams] = None,
) -> List[Feedback]:
    """
    Feedback rows, newest first, filtered by the denormalised attribution.

    An unknown id yields an empty list — a filter that matches nothing is a
    valid answer. Rows written before attribution existed have NULL in these
    columns and therefore match neither filter.
    """
    query = db.query(Feedback)

    if employee_id is not None:
        query = query.filter(Feedback.employee_id == employee_id)

    if department_id is not None:
        query = query.filter(Feedback.department_id == department_id)

    query = query.order_by(Feedback.created_at.desc())

    if page is not None:
        query = page.apply(query)

    return query.all()
