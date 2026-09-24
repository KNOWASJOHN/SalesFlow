import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CampaignCreate(BaseModel):
    campaign_code: str
    name: str
    department_id: Optional[uuid.UUID] = None
    campaign_team: str


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    campaign_id: uuid.UUID
    campaign_code: str
    name: str
    department_id: Optional[uuid.UUID] = None
    campaign_team: str