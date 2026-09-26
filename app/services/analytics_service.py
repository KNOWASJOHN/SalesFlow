"""
Read-only aggregation queries behind ``/api/v1/analytics/*``.

Everything here is a COUNT/SUM/AVG over tables the write paths already fill —
no side effects, no caching, safe to call on every dashboard refresh. The
functions return plain dicts and the routers attach the response schemas, so a
query can be tested without going through HTTP.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from app.models.ad_event import AdEvent
from app.models.campaign import Campaign
from app.models.department import Department
from app.models.employee import Employee
from app.models.employee_points import EmployeePoint
from app.models.feedback import Feedback
from app.models.interaction import Interaction
from app.models.journey import Journey
from app.models.purchase import Purchase


def _average(value: Any) -> Optional[float]:
    """Round a SQL AVG result; None when every contributing value was NULL."""
    if value is None:
        return None

    return round(float(value), 2)


def _today_window() -> tuple:
    """
    The half-open UTC window covering today: ``[00:00 today, 00:00 tomorrow)``.

    Half-open rather than 00:00:00-to-23:59:59 so a row stamped exactly at
    midnight belongs to one day only, and so both bounds can use the column
    index instead of a date() cast over every row.
    """
    start_of_today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    return start_of_today, start_of_today + timedelta(days=1)


def feedback_by_department(db: Session) -> List[Dict[str, Any]]:
    """
    Average ratings grouped by the department the feedback was attributed to.

    Inner join, so the NULL-attribution rows written before attribution existed
    are simply absent instead of appearing as a "" department. Departments with
    no feedback are absent too — an empty list means "nothing rated yet", not an
    error, and inventing zero rows would drag every average down.
    """
    rows = (
        db.query(
            Feedback.department_id,
            Department.name,
            func.count(Feedback.feedback_id),
            func.avg(Feedback.overall_rating),
            func.avg(Feedback.department_rating),
            func.avg(Feedback.employee_rating),
        )
        .join(Department, Department.department_id == Feedback.department_id)
        .group_by(Feedback.department_id, Department.name)
        .order_by(Department.name)
        .all()
    )

    return [
        {
            "department_id": department_id,
            "department_name": name,
            "feedback_count": count,
            "average_overall_rating": _average(overall),
            "average_department_rating": _average(department),
            "average_employee_rating": _average(employee),
        }
        for department_id, name, count, overall, department, employee in rows
    ]


def feedback_by_employee(db: Session) -> List[Dict[str, Any]]:
    """Average ratings grouped by the employee the feedback was attributed to."""
    rows = (
        db.query(
            Feedback.employee_id,
            Employee.name,
            Employee.employee_code,
            Employee.department_id,
            func.count(Feedback.feedback_id),
            func.avg(Feedback.overall_rating),
            func.avg(Feedback.department_rating),
            func.avg(Feedback.employee_rating),
        )
        .join(Employee, Employee.employee_id == Feedback.employee_id)
        .group_by(
            Feedback.employee_id,
            Employee.name,
            Employee.employee_code,
            Employee.department_id,
        )
        .order_by(Employee.name)
        .all()
    )

    return [
        {
            "employee_id": employee_id,
            "employee_name": name,
            "employee_code": code,
            "department_id": department_id,
            "feedback_count": count,
            "average_overall_rating": _average(overall),
            "average_department_rating": _average(department),
            "average_employee_rating": _average(employee),
        }
        for employee_id, name, code, department_id, count, overall, department, employee in rows
    ]


def overview(db: Session, active_calls: int) -> Dict[str, Any]:
    """
    The dashboard's headline numbers.

    ``active_calls`` is passed in rather than queried here: call state lives in
    the signaling process' memory, and the one definition of "active call" is
    the calls service both this tile and /calls/active read from.
    """
    start_of_today, start_of_tomorrow = _today_window()

    today = (
        Purchase.purchased_at >= start_of_today,
        Purchase.purchased_at < start_of_tomorrow,
    )

    active_employees = (
        db.query(func.count(Employee.employee_id))
        .filter(Employee.is_online.is_(True))
        .scalar()
        or 0
    )

    purchases_today = (
        db.query(func.count(Purchase.purchase_id)).filter(*today).scalar() or 0
    )

    revenue_today = (
        db.query(func.coalesce(func.sum(Purchase.amount), 0)).filter(*today).scalar()
    )

    points_awarded_today = (
        db.query(func.coalesce(func.sum(EmployeePoint.points), 0))
        .filter(
            EmployeePoint.created_at >= start_of_today,
            EmployeePoint.created_at < start_of_tomorrow,
        )
        .scalar()
    )

    return {
        "active_employees": int(active_employees),
        "active_calls": int(active_calls),
        "purchases_today": int(purchases_today),
        "revenue_today": float(revenue_today),
        "points_awarded_today": int(points_awarded_today),
    }


def campaign_funnel(
    db: Session,
    campaign_id: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    """
    Ad events, journeys and purchases attributed to one campaign.

    Returns None for an unknown campaign so the router can answer 404 — an
    all-zero funnel for a campaign that does not exist would be a lie.

    The stages are counted independently. Nothing in the schema forces a click
    to precede a journey or a journey to precede a purchase, so the numbers are
    only non-increasing when the underlying data was recorded in order.
    """
    campaign = (
        db.query(Campaign).filter(Campaign.campaign_id == campaign_id).first()
    )

    if campaign is None:
        return None

    event_counts = dict(
        db.query(AdEvent.event_type, func.count(AdEvent.ad_event_id))
        .filter(AdEvent.campaign_id == campaign_id)
        .group_by(AdEvent.event_type)
        .all()
    )

    journeys = (
        db.query(func.count(Journey.journey_id))
        .filter(Journey.campaign_id == campaign_id)
        .scalar()
        or 0
    )

    purchases = (
        db.query(func.count(Purchase.purchase_id))
        .join(Journey, Journey.journey_id == Purchase.journey_id)
        .filter(Journey.campaign_id == campaign_id)
        .scalar()
        or 0
    )

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign.name,
        "impressions": int(event_counts.get("impression", 0)),
        "clicks": int(event_counts.get("click", 0)),
        "landings": int(event_counts.get("landing", 0)),
        "leads": int(event_counts.get("lead", 0)),
        "journeys": int(journeys),
        "purchases": int(purchases),
    }


def employee_leaderboard(db: Session) -> List[Dict[str, Any]]:
    """
    Employees by total points, highest first.

    An outer join, so an employee with no points yet still appears with 0 —
    the leaderboard is a roster as well as a ranking. Ties share the rank of
    the first employee in the tie and the next distinct score skips ahead
    (1, 1, 3).
    """
    total_points = func.coalesce(func.sum(EmployeePoint.points), 0)

    rows = (
        db.query(
            Employee.employee_id,
            Employee.employee_code,
            Employee.name,
            Employee.department_id,
            total_points,
        )
        .outerjoin(EmployeePoint, EmployeePoint.employee_id == Employee.employee_id)
        .group_by(
            Employee.employee_id,
            Employee.employee_code,
            Employee.name,
            Employee.department_id,
        )
        .order_by(total_points.desc(), Employee.name)
        .all()
    )

    leaderboard = []
    rank = 0
    previous_total = None

    for position, (employee_id, code, name, department_id, total) in enumerate(rows, start=1):
        total = int(total)

        if previous_total is None or total != previous_total:
            rank = position
            previous_total = total

        leaderboard.append(
            {
                "rank": rank,
                "employee_id": employee_id,
                "employee_code": code,
                "employee_name": name,
                "department_id": department_id,
                "total_points": total,
            }
        )

    return leaderboard


def employee_performance(
    db: Session,
    employee_id: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    """
    Points, workload and conversion for one employee.

    ``conversion_rate`` is a fraction of the journeys this employee touched that
    ended in a purchase, and is 0.0 when they touched none — there is no rate
    without a denominator, and zero is the honest reading of that.
    """
    employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()

    if employee is None:
        return None

    total = (
        db.query(func.coalesce(func.sum(EmployeePoint.points), 0))
        .filter(EmployeePoint.employee_id == employee_id)
        .scalar()
    )

    interaction_count = (
        db.query(func.count(Interaction.interaction_id))
        .filter(Interaction.employee_id == employee_id)
        .scalar()
        or 0
    )

    journeys_touched = (
        db.query(func.count(func.distinct(Interaction.journey_id)))
        .filter(Interaction.employee_id == employee_id)
        .scalar()
        or 0
    )

    journeys_purchased = (
        db.query(func.count(func.distinct(Interaction.journey_id)))
        .join(Journey, Journey.journey_id == Interaction.journey_id)
        .filter(Interaction.employee_id == employee_id, Journey.purchased.is_(True))
        .scalar()
        or 0
    )

    conversion_rate = 0.0
    if journeys_touched:
        conversion_rate = round(journeys_purchased / journeys_touched, 4)

    return {
        "employee_id": employee.employee_id,
        "employee_code": employee.employee_code,
        "employee_name": employee.name,
        "department_id": employee.department_id,
        "total_points": int(total),
        "interaction_count": int(interaction_count),
        "journeys_touched": int(journeys_touched),
        "journeys_purchased": int(journeys_purchased),
        "conversion_rate": conversion_rate,
    }


def transfer_paths(db: Session) -> List[Dict[str, Any]]:
    """
    How often customers move between departments, most common first.

    "From" is the department of the employee who transferred (resolved through
    ``interactions.transfer_from_employee_id``), "to" is the department the new
    interaction was created in. The pair is the interesting part: it shows which
    hand-offs the org actually performs, and which one-way pairs may be missing
    an opposite route.
    """
    transferring_employee = aliased(Employee)
    from_department = aliased(Department)
    to_department = aliased(Department)

    transfer_count = func.count(Interaction.interaction_id)

    rows = (
        db.query(
            transferring_employee.department_id,
            from_department.name,
            Interaction.department_id,
            to_department.name,
            transfer_count,
        )
        .join(
            transferring_employee,
            transferring_employee.employee_id == Interaction.transfer_from_employee_id,
        )
        .join(
            from_department,
            from_department.department_id == transferring_employee.department_id,
        )
        .join(
            to_department,
            to_department.department_id == Interaction.department_id,
        )
        .group_by(
            transferring_employee.department_id,
            from_department.name,
            Interaction.department_id,
            to_department.name,
        )
        .order_by(transfer_count.desc())
        .all()
    )

    return [
        {
            "from_department_id": from_id,
            "from_department_name": from_name,
            "to_department_id": to_id,
            "to_department_name": to_name,
            "transfer_count": int(count),
        }
        for from_id, from_name, to_id, to_name, count in rows
    ]
