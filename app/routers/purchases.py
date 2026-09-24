import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.customer import Customer
from app.models.journey import Journey
from app.models.purchase import Purchase
from app.schemas.purchase import PurchaseCreate, PurchaseOut


router = APIRouter(
    prefix="/api/v1/journeys",
    tags=["Purchases"]
)


@router.post(
    "/{journey_id}/purchase",
    response_model=PurchaseOut,
    status_code=status.HTTP_201_CREATED
)
def create_purchase(
    journey_id: uuid.UUID,
    payload: PurchaseCreate,
    db: Session = Depends(get_db)
):
    journey = (
        db.query(Journey)
        .filter(Journey.journey_id == journey_id)
        .first()
    )

    if journey is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "JOURNEY_NOT_FOUND",
                "message": "The requested journey does not exist."
            }
        )

    if journey.status != "active":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "JOURNEY_NOT_ACTIVE",
                "message": "A purchase can only be recorded for an active journey."
            }
        )

    if journey.purchased:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "PURCHASE_ALREADY_RECORDED",
                "message": "This journey already has a purchase."
            }
        )

    customer = (
        db.query(Customer)
        .filter(Customer.customer_id == journey.customer_id)
        .first()
    )

    if customer is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "CUSTOMER_NOT_FOUND",
                "message": "The customer associated with this journey does not exist."
            }
        )

    purchase = Purchase(
        journey_id=journey.journey_id,
        customer_id=customer.customer_id,
        product_category=payload.product_category,
        amount=payload.amount
    )

    db.add(purchase)

    journey.purchased = True
    journey.status = "completed"

    if journey.ended_at is None:
        from datetime import datetime, timezone
        journey.ended_at = datetime.now(timezone.utc)

    try:
        db.commit()
        db.refresh(purchase)

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=409,
            detail={
                "error": "PURCHASE_ALREADY_EXISTS",
                "message": "A purchase already exists for this journey."
            }
        )

    return purchase