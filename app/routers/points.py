import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.employee import Employee
from app.schemas.points import EmployeePointsTotal, PointEntry
from app.services import points_service

router = APIRouter(
    prefix="/api/v1/employees",
    tags=["Points"]
)

@router.get(
    "/{employee_id}/points",
    response_model=EmployeePointsTotal,
    status_code=status.HTTP_200_OK
)
def get_points(
    employee_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not employee:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "EMPLOYEE_NOT_FOUND",
                "message": "The requested employee does not exist."
            }
        )
        
    total = points_service.get_employee_total_points(db, employee_id)
    return EmployeePointsTotal(employee_id=employee_id, total_points=total)


@router.get(
    "/{employee_id}/points/history",
    response_model=List[PointEntry],
    status_code=status.HTTP_200_OK
)
def get_points_history(
    employee_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not employee:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "EMPLOYEE_NOT_FOUND",
                "message": "The requested employee does not exist."
            }
        )
        
    history = points_service.get_employee_points_history(db, employee_id)
    return history
