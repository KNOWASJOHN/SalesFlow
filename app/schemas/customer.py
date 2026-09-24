import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CustomerCreate(BaseModel):
    contact_number: str
    age_group: Optional[str] = None
    occupation: Optional[str] = None
    location_type: Optional[str] = None
    budget_range: Optional[str] = None
    interested_category: Optional[str] = None
    purchase_intent: Optional[str] = None
    previous_customer: bool = False


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: uuid.UUID
    contact_number: str
    age_group: Optional[str] = None
    occupation: Optional[str] = None
    location_type: Optional[str] = None
    budget_range: Optional[str] = None
    interested_category: Optional[str] = None
    purchase_intent: Optional[str] = None
    previous_customer: bool