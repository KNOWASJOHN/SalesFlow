import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PurchaseCreate(BaseModel):
    product_category: str
    amount: Decimal = Field(..., ge=0)


class PurchaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    purchase_id: uuid.UUID
    journey_id: uuid.UUID
    customer_id: uuid.UUID
    product_category: str
    amount: Decimal
    purchased_at: datetime