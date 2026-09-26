import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.pagination import PageParams, page_params
from app.models.interaction import Interaction
from app.schemas.interaction import (
    InteractionStart,
    InteractionOut,
    InteractionEndOut,
    TransferRequest,
    TransferOut,
)
from app.services import journey_service

router = APIRouter(prefix="/api/v1", tags=["interactions"])


@router.get("/interactions", response_model=List[InteractionOut])
def list_interactions(
    employee_id: Optional[uuid.UUID] = Query(
        default=None,
        description="Only interactions handled by this employee.",
    ),
    department_id: Optional[uuid.UUID] = Query(
        default=None,
        description="Only interactions handled in this department.",
    ),
    journey_id: Optional[uuid.UUID] = Query(
        default=None,
        description="Only interactions belonging to this journey.",
    ),
    page: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    """
    Interaction history, newest first.

    ``?employee_id=`` is what the dashboard's Interaction History page reads:
    every interaction an employee handled, including the ones they received
    through a transfer.
    """
    query = db.query(Interaction)

    if employee_id is not None:
        query = query.filter(Interaction.employee_id == employee_id)

    if department_id is not None:
        query = query.filter(Interaction.department_id == department_id)

    if journey_id is not None:
        query = query.filter(Interaction.journey_id == journey_id)

    return page.apply(query.order_by(Interaction.started_at.desc())).all()


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
