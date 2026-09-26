import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.pagination import PageParams, page_params
from app.models.customer import Customer
from app.models.journey import Journey
from app.models.purchase import Purchase
from app.schemas.purchase import PurchaseCreate, PurchaseOut
from app.services.points_service import process_purchase_points


router = APIRouter(
    prefix="/api/v1/journeys",
    tags=["Purchases"]
)

# The purchase *list* is not scoped to a journey, so it cannot hang off the
# journey-scoped router above. Same module, second router.
purchase_list_router = APIRouter(
    prefix="/api/v1",
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
        journey.ended_at = datetime.now(timezone.utc)

    # The points the purchase earns are added to the same transaction and the
    # single commit below writes both, so a journey can never end up marked as
    # purchased without the points that purchase is worth.
    process_purchase_points(db, journey.journey_id)

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


@purchase_list_router.get("/purchases", response_model=List[PurchaseOut])
def list_purchases(
    product_category: Optional[str] = Query(
        default=None,
        description="Exact product category to filter by.",
    ),
    purchased_after: Optional[datetime] = Query(
        default=None,
        description="Inclusive lower bound on purchased_at (ISO 8601).",
    ),
    purchased_before: Optional[datetime] = Query(
        default=None,
        description="Inclusive upper bound on purchased_at (ISO 8601).",
    ),
    page: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    """
    Purchases over a time window, newest first.

    Revenue and purchase-count tiles read this; the window is inclusive on both
    ends so a whole day is ``?purchased_after=<00:00>&purchased_before=<23:59:59>``.
    """
    query = db.query(Purchase)

    if product_category is not None:
        query = query.filter(Purchase.product_category == product_category)

    if purchased_after is not None:
        query = query.filter(Purchase.purchased_at >= purchased_after)

    if purchased_before is not None:
        query = query.filter(Purchase.purchased_at <= purchased_before)

    return page.apply(query.order_by(Purchase.purchased_at.desc())).all()