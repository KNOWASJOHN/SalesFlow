import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class InteractionStart(BaseModel):
    employee_id: uuid.UUID
    department_id: uuid.UUID


class InteractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    interaction_id: uuid.UUID
    journey_id: uuid.UUID
    employee_id: uuid.UUID
    department_id: uuid.UUID
    interaction_order: int
    started_at: datetime | None = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    outcome: Optional[str] = None


class InteractionEndOut(BaseModel):
    interaction_id: uuid.UUID
    ended_at: datetime
    duration_seconds: int
    outcome: Optional[str] = None


class TransferRequest(BaseModel):
    department_id: uuid.UUID


class TransferOut(BaseModel):
    transferred: bool
    new_employee_id: uuid.UUID
    new_interaction_id: uuid.UUID