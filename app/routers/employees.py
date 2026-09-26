import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.pagination import PageParams, page_params
from app.models.employee import Employee
from app.schemas.employee import EmployeeOut

router = APIRouter(prefix="/api/v1/employees", tags=["employees"])


@router.get("", response_model=List[EmployeeOut])
def list_employees(
    department_id: Optional[uuid.UUID] = Query(
        default=None,
        description="Only employees belonging to this department.",
    ),
    is_online: Optional[bool] = Query(
        default=None,
        description="true returns only currently-online employees, the pool "
        "/available-employees picks from; false returns only offline ones.",
    ),
    page: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    """
    The employee roster, optionally filtered.

    An unknown ``department_id`` yields an empty list rather than a 404: a
    filter that matches nothing is a valid answer, unlike a single-item GET.
    """
    query = db.query(Employee)

    if department_id is not None:
        query = query.filter(Employee.department_id == department_id)

    if is_online is not None:
        query = query.filter(Employee.is_online == is_online)

    return page.apply(query.order_by(Employee.employee_code)).all()


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: uuid.UUID, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()

    if not employee:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "EMPLOYEE_NOT_FOUND",
                "message": "No employee with this ID exists.",
            },
        )

    return employee
