import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.customer import Customer
from app.models.journey import Journey
from app.models.feedback import Feedback
from app.models.interaction import Interaction
from app.schemas.feedback import FeedbackCreate, FeedbackOut


router = APIRouter(
    prefix="/api/v1/journeys",
    tags=["Feedback"]
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

    if journey.status not in ("completed", "cancelled"):
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

    feedback = Feedback(
        journey_id=journey.journey_id,
        customer_id=customer.customer_id,
        feedback_type="overall",
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
    db.commit()
    db.refresh(feedback)

    return feedback