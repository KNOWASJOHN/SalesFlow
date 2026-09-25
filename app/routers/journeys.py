import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.journey import Journey
from app.models.customer import Customer
from app.models.campaign import Campaign
from app.schemas.journey import JourneyCreate, JourneyCreateOut, JourneyEndOut, JourneyOut

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


@router.post("/{journey_id}/abandon", response_model=JourneyEndOut)
def abandon_journey(journey_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Close a journey that ended without a purchase.

    A purchase is the only other way a journey reaches a terminal state, so
    without this a customer who walked away could never be asked to review the
    visit — exactly the case ``reason_for_not_purchasing`` exists for.
    """
    journey = db.query(Journey).filter(Journey.journey_id == journey_id).first()
    if not journey:
        raise HTTPException(
            status_code=404,
            detail={"error": "JOURNEY_NOT_FOUND", "message": "No journey with this ID exists."},
        )

    if journey.status != "active":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "INVALID_STATE",
                "message": f"A journey with status '{journey.status}' cannot be abandoned.",
            },
        )

    journey.status = "abandoned"
    journey.ended_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(journey)

    return JourneyEndOut(
        journey_id=journey.journey_id,
        status=journey.status,
        ended_at=journey.ended_at,
    )


@router.get("/{journey_id}", response_model=JourneyOut)
def get_journey(journey_id: uuid.UUID, db: Session = Depends(get_db)):
    journey = db.query(Journey).filter(Journey.journey_id == journey_id).first()
    if not journey:
        raise HTTPException(
            status_code=404,
            detail={"error": "JOURNEY_NOT_FOUND", "message": "No journey with this ID exists."},
        )
    return journey