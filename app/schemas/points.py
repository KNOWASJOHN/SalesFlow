import uuid
from typing import List
from pydantic import BaseModel, ConfigDict
from datetime import datetime

class EmployeePointsTotal(BaseModel):
    employee_id: uuid.UUID
    total_points: int
    
class PointEntry(BaseModel):
    point_entry_id: uuid.UUID
    journey_id: uuid.UUID
    employee_id: uuid.UUID
    points: int
    reason: str
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
