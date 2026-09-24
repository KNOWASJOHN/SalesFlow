import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.campaign import Campaign
from app.models.ad_event import AdEvent
from app.schemas.campaign import CampaignCreate, CampaignOut
from app.schemas.ad_event import AdEventCreate, AdEventOut

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])


@router.post("", response_model=CampaignOut, status_code=201)
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    existing = db.query(Campaign).filter(
        Campaign.campaign_code == payload.campaign_code
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "CAMPAIGN_ALREADY_EXISTS",
                "message": "A campaign with this campaign_code already exists.",
            },
        )

    campaign = Campaign(**payload.model_dump())
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.get("", response_model=List[CampaignOut])
def list_campaigns(db: Session = Depends(get_db)):
    return db.query(Campaign).all()


@router.get("/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.campaign_id == campaign_id).first()
    if not campaign:
        raise HTTPException(
            status_code=404,
            detail={"error": "CAMPAIGN_NOT_FOUND", "message": "No campaign with this ID exists."},
        )
    return campaign


@router.post("/{campaign_id}/events", response_model=AdEventOut, status_code=201)
def record_ad_event(campaign_id: uuid.UUID, payload: AdEventCreate, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.campaign_id == campaign_id).first()
    if not campaign:
        raise HTTPException(
            status_code=404,
            detail={"error": "CAMPAIGN_NOT_FOUND", "message": "No campaign with this ID exists."},
        )

    valid_types = {"impression", "click", "landing", "lead"}
    if payload.event_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_EVENT_TYPE",
                "message": f"event_type must be one of {sorted(valid_types)}.",
            },
        )

    event = AdEvent(campaign_id=campaign_id, **payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event