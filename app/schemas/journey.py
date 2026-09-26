import uuid
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class JourneyCreate(BaseModel):
    customer_id: uuid.UUID
    campaign_id: Optional[uuid.UUID] = None


class JourneyCreateOut(BaseModel):
    journey_id: uuid.UUID
    status: str


class JourneyEndOut(BaseModel):
    journey_id: uuid.UUID
    status: str
    ended_at: datetime


class InteractionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    interaction_id: uuid.UUID
    employee_id: uuid.UUID
    department_id: uuid.UUID
    interaction_order: int
    started_at: datetime
    ended_at: Optional[datetime] = None


class JourneyListOut(BaseModel):
    """One row of a paginated journey list, without the interaction children."""

    model_config = ConfigDict(from_attributes=True)

    journey_id: uuid.UUID
    customer_id: uuid.UUID
    campaign_id: Optional[uuid.UUID] = None
    status: str
    purchased: bool
    started_at: datetime
    ended_at: Optional[datetime] = None


class JourneyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    journey_id: uuid.UUID
    customer_id: uuid.UUID
    campaign_id: Optional[uuid.UUID] = None
    status: str
    purchased: bool
    started_at: datetime
    ended_at: Optional[datetime] = None
    interactions: List[InteractionSummary] = []
    # purchase / feedback / points stay absent until Modules 6-7 add them


class EmployeeAvailable(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: uuid.UUID
    employee_code: str
    name: str
    department_id: uuid.UUID