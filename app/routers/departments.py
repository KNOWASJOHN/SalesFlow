import uuid
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.journey import EmployeeAvailable
from app.services.assignment_service import get_next_available_employee

router = APIRouter(prefix="/api/v1/departments", tags=["departments"])


@router.get("/{department_id}/available-employees", response_model=EmployeeAvailable)
def get_available_employee(department_id: uuid.UUID, db: Session = Depends(get_db)):
    employee = get_next_available_employee(db, department_id)
    return employee