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

    Does not commit: the caller owns the transaction, so the purchase row and
    the points it earns are written or rolled back together.
    """
    interactions = db.query(Interaction).filter(Interaction.journey_id == journey_id).all()
    
    employee_stats = {}
    for i in interactions:
        if i.employee_id not in employee_stats:
            employee_stats[i.employee_id] = {"interactions": 0, "transfers": 0}
        employee_stats[i.employee_id]["interactions"] += 1
        if i.transfer_to_employee_id:
            employee_stats[i.employee_id]["transfers"] += 1

    for emp_id, stats in employee_stats.items():
        db.add(
            EmployeePoint(
                journey_id=journey_id,
                employee_id=emp_id,
                points=POINT_FORMULA["purchase"],
                reason="Journey purchased"
            )
        )
        
        if stats["interactions"] > 0:
            db.add(
                EmployeePoint(
                    journey_id=journey_id,
                    employee_id=emp_id,
                    points=POINT_FORMULA["interaction"] * stats["interactions"],
                    reason=f"Participated in {stats['interactions']} interaction(s)"
                )
            )
            
        if stats["transfers"] > 0:
            db.add(
                EmployeePoint(
                    journey_id=journey_id,
                    employee_id=emp_id,
                    points=POINT_FORMULA["transfer"] * stats["transfers"],
                    reason=f"Initiated {stats['transfers']} transfer(s)"
                )
            )

    db.flush()


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
    employee_ids = {i.employee_id for i in interactions}
    
    for emp_id in employee_ids:
        db.add(
            EmployeePoint(
                journey_id=feedback.journey_id,
                employee_id=emp_id,
                points=points,
                reason=reason
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
