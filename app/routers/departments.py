import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.department import Department
from app.schemas.department import DepartmentOut
from app.schemas.journey import EmployeeAvailable
from app.services.assignment_service import get_next_available_employee

router = APIRouter(prefix="/api/v1/departments", tags=["departments"])


@router.get("", response_model=List[DepartmentOut])
def list_departments(db: Session = Depends(get_db)):
    """
    Every department.

    Departments are admin-seeded org data, so this is read-only and unpaginated:
    the roster is small and the dashboard uses it for filter dropdowns as much
    as for the list itself.
    """
    return db.query(Department).order_by(Department.name).all()


@router.get("/{department_id}", response_model=DepartmentOut)
def get_department(department_id: uuid.UUID, db: Session = Depends(get_db)):
    department = db.query(Department).filter(Department.department_id == department_id).first()

    if not department:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "DEPARTMENT_NOT_FOUND",
                "message": "No department with this ID exists.",
            },
        )

    return department


@router.get("/{department_id}/available-employees", response_model=EmployeeAvailable)
def get_available_employee(department_id: uuid.UUID, db: Session = Depends(get_db)):
    employee = get_next_available_employee(db, department_id)
    return employee
