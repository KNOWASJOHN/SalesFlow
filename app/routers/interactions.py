import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.interaction import (
    InteractionStart,
    InteractionOut,
    InteractionEndOut,
    TransferRequest,
    TransferOut,
)
from app.services import journey_service

router = APIRouter(prefix="/api/v1", tags=["interactions"])


@router.post("/journeys/{journey_id}/interactions", response_model=InteractionOut, status_code=201)
def create_interaction(journey_id: uuid.UUID, payload: InteractionStart, db: Session = Depends(get_db)):
    interaction = journey_service.start_interaction(
        db, journey_id=journey_id, employee_id=payload.employee_id, department_id=payload.department_id
    )
    return interaction


@router.post("/interactions/{interaction_id}/end", response_model=InteractionEndOut)
def end_interaction(interaction_id: uuid.UUID, db: Session = Depends(get_db)):
    interaction = journey_service.end_interaction(db, interaction_id=interaction_id)
    return InteractionEndOut(
        interaction_id=interaction.interaction_id,
        ended_at=interaction.ended_at,
        duration_seconds=interaction.duration_seconds,
        outcome=interaction.outcome,
    )


@router.post("/interactions/{interaction_id}/transfer", response_model=TransferOut)
def transfer_interaction(interaction_id: uuid.UUID, payload: TransferRequest, db: Session = Depends(get_db)):
    result = journey_service.transfer_interaction(db, interaction_id=interaction_id, department_id=payload.department_id)
    return result
