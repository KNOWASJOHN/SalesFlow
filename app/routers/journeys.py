import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, lazyload

from app.core.database import get_db
from app.core.pagination import PageParams, page_params
from app.models.journey import Journey
from app.models.customer import Customer
from app.models.campaign import Campaign
from app.schemas.journey import (
    JourneyCreate,
    JourneyCreateOut,
    JourneyEndOut,
    JourneyListOut,
    JourneyOut,
)

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


@router.get("", response_model=List[JourneyListOut])
def list_journeys(
    customer_id: Optional[uuid.UUID] = Query(
        default=None,
        description="Only journeys belonging to this customer.",
    ),
    campaign_id: Optional[uuid.UUID] = Query(
        default=None,
        description="Only journeys attributed to this campaign.",
    ),
    status: Optional[str] = Query(
        default=None,
        description="active | completed | abandoned.",
    ),
    started_after: Optional[datetime] = Query(
        default=None,
        description="Inclusive lower bound on started_at (ISO 8601).",
    ),
    started_before: Optional[datetime] = Query(
        default=None,
        description="Inclusive upper bound on started_at (ISO 8601).",
    ),
    page: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    """
    Browsable journey list for the dashboard, newest first.

    Filters that match nothing return an empty list. The per-journey interaction
    list is deliberately not included here: this endpoint is paginated, and the
    joined eager load the single-journey GET relies on would apply the page
    window to the joined rows instead of to the journeys.
    """
    query = db.query(Journey).options(lazyload(Journey.interactions))

    if customer_id is not None:
        query = query.filter(Journey.customer_id == customer_id)

    if campaign_id is not None:
        query = query.filter(Journey.campaign_id == campaign_id)

    if status is not None:
        query = query.filter(Journey.status == status)

    if started_after is not None:
        query = query.filter(Journey.started_at >= started_after)

    if started_before is not None:
        query = query.filter(Journey.started_at <= started_before)

    return page.apply(query.order_by(Journey.started_at.desc())).all()


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