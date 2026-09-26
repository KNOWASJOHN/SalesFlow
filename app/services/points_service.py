import uuid
from typing import Dict, List, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.employee_points import EmployeePoint
from app.models.interaction import Interaction
from app.models.feedback import Feedback
from app.models.employee import Employee


POINT_FORMULA = {
    "purchase": 50,
    "good_rating": 20,
    "bad_rating": -10,
    "interaction": 10,
    "transfer": 5
}


def process_purchase_points(db: Session, journey_id: uuid.UUID):
    """
    Award purchase, interaction and transfer points for a journey's employees.

    Every award lands in ``employee_points`` as its own row: the running total is
    SUM(points) over that table, so the ledger and the total cannot disagree.
    Each row also carries a ``reason_code`` and, where the award is about one
    specific interaction, that interaction's id.

    Does not commit: the caller owns the transaction, so the purchase row and
    the points it earns are written or rolled back together.
    """
    interactions = db.query(Interaction).filter(Interaction.journey_id == journey_id).all()

    employee_stats = {}
    for i in interactions:
        if i.employee_id not in employee_stats:
            employee_stats[i.employee_id] = {
                "interactions": 0,
                "transfers": 0,
                "interaction_ids": [],
                "transfer_interaction_ids": [],
            }
        employee_stats[i.employee_id]["interactions"] += 1
        employee_stats[i.employee_id]["interaction_ids"].append(i.interaction_id)
        if i.transfer_to_employee_id:
            employee_stats[i.employee_id]["transfers"] += 1
            employee_stats[i.employee_id]["transfer_interaction_ids"].append(i.interaction_id)

    for emp_id, stats in employee_stats.items():
        db.add(
            EmployeePoint(
                journey_id=journey_id,
                employee_id=emp_id,
                points=POINT_FORMULA["purchase"],
                reason="Journey purchased",
                reason_code="purchase"
            )
        )

        if stats["interactions"] > 0:
            db.add(
                EmployeePoint(
                    journey_id=journey_id,
                    employee_id=emp_id,
                    points=POINT_FORMULA["interaction"] * stats["interactions"],
                    reason=f"Participated in {stats['interactions']} interaction(s)",
                    reason_code="interaction",
                    # One row covers every interaction this employee handled, so
                    # it can only name one of them when there is exactly one;
                    # otherwise the row is an aggregate and points at nothing.
                    related_interaction_id=_sole_id(stats["interaction_ids"])
                )
            )

        if stats["transfers"] > 0:
            db.add(
                EmployeePoint(
                    journey_id=journey_id,
                    employee_id=emp_id,
                    points=POINT_FORMULA["transfer"] * stats["transfers"],
                    reason=f"Initiated {stats['transfers']} transfer(s)",
                    reason_code="transfer",
                    related_interaction_id=_sole_id(stats["transfer_interaction_ids"])
                )
            )

    db.flush()


def _sole_id(interaction_ids: List[uuid.UUID]):
    """The one id in the list, or None when the row aggregates several."""
    if len(interaction_ids) == 1:
        return interaction_ids[0]

    return None


def process_feedback_points(db: Session, feedback: Feedback):
    """
    Award rating points for a journey's employees.

    Does not commit: the caller owns the transaction, so the feedback row and
    the points it earns are written or rolled back together. A neutral rating
    (3) awards nothing, which is why the ``points <> 0`` constraint stays safe.
    """
    if not feedback.overall_rating:
        return

    rating = feedback.overall_rating
    if rating >= 4:
        points = POINT_FORMULA["good_rating"]
        reason = "Good overall feedback rating"
    elif rating <= 2:
        points = POINT_FORMULA["bad_rating"]
        reason = "Poor overall feedback rating"
    else:
        return

    interactions = db.query(Interaction).filter(Interaction.journey_id == feedback.journey_id).all()

    # Each employee is credited once, against the interaction they actually
    # finished the journey on — the same attribution the feedback row itself
    # uses, so a transfer credits the receiving employee's own interaction.
    latest_by_employee = {}
    for interaction in interactions:
        current = latest_by_employee.get(interaction.employee_id)
        if current is None or interaction.interaction_order > current.interaction_order:
            latest_by_employee[interaction.employee_id] = interaction

    for emp_id, interaction in latest_by_employee.items():
        db.add(
            EmployeePoint(
                journey_id=feedback.journey_id,
                employee_id=emp_id,
                points=points,
                reason=reason,
                reason_code="rating",
                related_interaction_id=interaction.interaction_id
            )
        )

    db.flush()


def get_employee_total_points(db: Session, employee_id: uuid.UUID) -> int:
    total = db.query(func.sum(EmployeePoint.points)).filter(EmployeePoint.employee_id == employee_id).scalar()
    return total or 0


def get_employee_points_history(db: Session, employee_id: uuid.UUID) -> List[EmployeePoint]:
    return (
        db.query(EmployeePoint)
        .filter(EmployeePoint.employee_id == employee_id)
        .order_by(EmployeePoint.created_at.desc())
        .all()
    )
