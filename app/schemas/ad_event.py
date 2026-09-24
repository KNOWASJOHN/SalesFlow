import uuid
from typing import Optional
from pydantic import BaseModel, ConfigDict


class AdEventCreate(BaseModel):
    customer_id: Optional[uuid.UUID] = None
    event_type: str  # "impression" | "click" | "landing" | "lead"
    session_reference: Optional[str] = None


class AdEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ad_event_id: uuid.UUID
    campaign_id: uuid.UUID
    customer_id: Optional[uuid.UUID] = None
    event_type: str
    session_reference: Optional[str] = None