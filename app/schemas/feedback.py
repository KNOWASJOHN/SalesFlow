import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FeedbackCreate(BaseModel):
    overall_rating: Optional[int] = Field(
        default=None,
        ge=1,
        le=5
    )

    employee_rating: Optional[int] = Field(
        default=None,
        ge=1,
        le=5
    )

    department_rating: Optional[int] = Field(
        default=None,
        ge=1,
        le=5
    )

    reason_for_not_purchasing: Optional[str] = None
    product_interest: Optional[str] = None
    price_concern: Optional[str] = None
    competitor_preference: Optional[str] = None
    general_feedback: Optional[str] = None


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feedback_id: uuid.UUID
    journey_id: uuid.UUID
    customer_id: uuid.UUID
    feedback_type: str
    employee_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None
    overall_rating: Optional[int] = None
    employee_rating: Optional[int] = None
    department_rating: Optional[int] = None
    reason_for_not_purchasing: Optional[str] = None
    product_interest: Optional[str] = None
    price_concern: Optional[str] = None
    competitor_preference: Optional[str] = None
    general_feedback: Optional[str] = None
    created_at: datetime