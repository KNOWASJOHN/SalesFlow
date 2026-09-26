import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EmployeeOut(BaseModel):
    """A row of the employee roster the Active Employees dashboard page lists."""

    model_config = ConfigDict(from_attributes=True)

    employee_id: uuid.UUID
    employee_code: str
    name: str
    role: str
    department_id: uuid.UUID
    is_online: bool
    created_at: datetime
