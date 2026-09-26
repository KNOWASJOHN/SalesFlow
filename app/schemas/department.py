import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    department_id: uuid.UUID
    name: str
    description: Optional[str] = None
