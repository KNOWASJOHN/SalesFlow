import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.journey import Journey
from app.models.customer import Customer
from app.models.campaign import Campaign
from app.schemas.journey import JourneyCreate, JourneyCreateOut, JourneyOut

router = APIRouter(prefix="/api/v1/journeys", tags=["journeys"])


@router.post("", response_model=JourneyCreateOut, status_code=201)
def start_journey(payload: JourneyCreate, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.customer_id == payload.customer_id).first()
    if not customer:
        raise HTTPException(
            status_code=404,
            detail={"error": "CUSTOMER_NOT_FOUND", "message": "No customer with this ID exists."},
        )

    if payload.campaign_id:
        campaign = db.query(Campaign).filter(Campaign.campaign_id == payload.campaign_id).first()
        if not campaign:
            raise HTTPException(
                status_code=404,
                detail={"error": "CAMPAIGN_NOT_FOUND", "message": "No campaign with this ID exists."},
            )

    journey = Journey(
        customer_id=payload.customer_id,
        campaign_id=payload.campaign_id,
        status="active",
    )
    db.add(journey)
    db.commit()
    db.refresh(journey)

    return JourneyCreateOut(journey_id=journey.journey_id, status=journey.status)


@router.get("/{journey_id}", response_model=JourneyOut)
def get_journey(journey_id: uuid.UUID, db: Session = Depends(get_db)):
    journey = db.query(Journey).filter(Journey.journey_id == journey_id).first()
    if not journey:
        raise HTTPException(
            status_code=404,
            detail={"error": "JOURNEY_NOT_FOUND", "message": "No journey with this ID exists."},
        )
    # journey.interactions requires a relationship; see note below
    return journey