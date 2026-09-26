import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.pagination import PageParams, page_params
from app.models.customer import Customer
from app.models.journey import Journey
from app.models.feedback import Feedback
from app.models.interaction import Interaction
from app.schemas.feedback import FeedbackCreate, FeedbackOut
from app.services import feedback_service
from app.services.points_service import process_feedback_points


router = APIRouter(
    prefix="/api/v1/journeys",
    tags=["Feedback"]
)

# The feedback *list* is not scoped to a journey, so it cannot hang off the
# journey-scoped router above. Same module, second router.
feedback_list_router = APIRouter(
    prefix="/api/v1",
    tags=["Feedback"]
)


@feedback_list_router.get("/feedback", response_model=List[FeedbackOut])
def list_feedback(
    employee_id: Optional[uuid.UUID] = Query(
        default=None,
        description="Only feedback attributed to this employee.",
    ),
    department_id: Optional[uuid.UUID] = Query(
        default=None,
        description="Only feedback attributed to this department.",
    ),
    page: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    """
    Feedback, newest first, filtered by who it is attributed to.

    Attribution is the employee and department the journey ended with, so after
    a transfer the feedback belongs to the receiving employee — that is the
    subset ``?employee_id=`` returns.
    """
    return feedback_service.list_feedback(
        db,
        employee_id=employee_id,
        department_id=department_id,
        page=page,
    )


@router.post(
    "/{journey_id}/feedback",
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED
)
def create_feedback(
    journey_id: uuid.UUID,
    payload: FeedbackCreate,
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

    # A journey reaches a terminal state either by purchase ("completed") or by
    # abandoning it without one ("abandoned"). Both are reviewable — a customer
    # who walked away is exactly who reason_for_not_purchasing is for.
    if journey.status not in ("completed", "abandoned"):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "JOURNEY_NOT_COMPLETED",
                "message": "Feedback can only be submitted after the journey has ended."
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

    existing_feedback = (
        db.query(Feedback)
        .filter(
            Feedback.journey_id == journey_id,
            Feedback.feedback_type == "overall"
        )
        .first()
    )

    if existing_feedback is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "FEEDBACK_ALREADY_SUBMITTED",
                "message": "Overall feedback has already been submitted for this journey."
            }
        )

    # Attribution is resolved here, inside the write, so every feedback row
    # carries the employee and department it is about from the moment it
    # exists. The journey's latest interaction is the one it ended on, which
    # after a transfer is the receiving employee, not the one who transferred.
    attributed_employee_id, attributed_department_id = feedback_service.resolve_attribution(
        db, journey.journey_id
    )

    feedback = Feedback(
        journey_id=journey.journey_id,
        customer_id=customer.customer_id,
        feedback_type="overall",
        employee_id=attributed_employee_id,
        department_id=attributed_department_id,
        overall_rating=payload.overall_rating,
        employee_rating=payload.employee_rating,
        department_rating=payload.department_rating,
        reason_for_not_purchasing=payload.reason_for_not_purchasing,
        product_interest=payload.product_interest,
        price_concern=payload.price_concern,
        competitor_preference=payload.competitor_preference,
        general_feedback=payload.general_feedback
    )

    db.add(feedback)

    # Same transaction as the feedback row, so a rating that awards points is
    # never stored without them.
    process_feedback_points(db, feedback)

    db.commit()
    db.refresh(feedback)

    return feedback