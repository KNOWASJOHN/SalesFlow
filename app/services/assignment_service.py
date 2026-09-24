from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException

from app.models.employee import Employee
from app.models.interaction import Interaction


def get_next_available_employee(db: Session, department_id) -> Employee:
    """
    Round-robin selection among online employees in a department.

    Stateless approach: pick the online employee whose most recent
    interaction (started_at) is oldest — or who has never had one at all.
    This naturally cycles through everyone without needing extra state
    that would be lost on server restart.
    """
    online_employees = (
        db.query(Employee)
        .filter(Employee.department_id == department_id, Employee.is_online == True)
        .all()
    )

    if not online_employees:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "EMPLOYEE_NOT_AVAILABLE",
                "message": "No online employee is available in the selected department.",
            },
        )

    # Map employee_id -> their most recent interaction start time
    last_assigned = dict(
        db.query(Interaction.employee_id, func.max(Interaction.started_at))
        .filter(Interaction.department_id == department_id)
        .group_by(Interaction.employee_id)
        .all()
    )

    # Employees never assigned sort first (None treated as "oldest")
    online_employees.sort(
        key=lambda emp: last_assigned.get(emp.employee_id) or __import__("datetime").datetime.min.replace(
            tzinfo=__import__("datetime").timezone.utc
        )
    )

    return online_employees[0]