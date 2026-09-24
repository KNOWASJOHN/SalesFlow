import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.interaction import Interaction
from app.models.journey import Journey
from app.services import assignment_service


def start_interaction(db: Session, journey_id: uuid.UUID, employee_id: uuid.UUID, department_id: uuid.UUID) -> Interaction:
    journey = db.query(Journey).filter(Journey.journey_id == journey_id).first()
    if not journey:
        raise HTTPException(
            status_code=404,
            detail={"error": "NOT_FOUND", "message": "Journey not found"}
        )

    last_interaction = (
        db.query(Interaction)
        .filter(Interaction.journey_id == journey_id)
        .order_by(Interaction.interaction_order.desc())
        .first()
    )
    order = 1
    if last_interaction:
        order = last_interaction.interaction_order + 1

    interaction = Interaction(
        journey_id=journey_id,
        employee_id=employee_id,
        department_id=department_id,
        interaction_order=order,
        started_at=datetime.now(timezone.utc)
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)
    return interaction


def end_interaction(db: Session, interaction_id: uuid.UUID) -> Interaction:
    interaction = db.query(Interaction).filter(Interaction.interaction_id == interaction_id).first()
    if not interaction:
        raise HTTPException(
            status_code=404,
            detail={"error": "NOT_FOUND", "message": "Interaction not found"}
        )

    if interaction.ended_at:
        raise HTTPException(
            status_code=409,
            detail={"error": "INVALID_STATE", "message": "Interaction is already ended."}
        )

    now = datetime.now(timezone.utc)
    interaction.ended_at = now

    if interaction.started_at:
        # PostgreSQL TIMESTAMP(timezone=True) gives timezone-aware datetimes.
        # But if it somehow doesn't, we might need to handle it.
        start_time = interaction.started_at
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
            
        duration = (now - start_time).total_seconds()
        interaction.duration_seconds = int(duration)
    else:
        interaction.duration_seconds = 0

    db.commit()
    db.refresh(interaction)
    return interaction


def transfer_interaction(db: Session, interaction_id: uuid.UUID, department_id: uuid.UUID) -> dict:
    current_interaction = db.query(Interaction).filter(Interaction.interaction_id == interaction_id).first()
    if not current_interaction:
        raise HTTPException(
            status_code=404,
            detail={"error": "NOT_FOUND", "message": "Interaction not found"}
        )

    if current_interaction.ended_at:
        raise HTTPException(
            status_code=409,
            detail={"error": "INVALID_STATE", "message": "Cannot transfer a closed interaction."}
        )

    # find next online employee in the target department
    next_employee = assignment_service.get_next_available_employee(db, department_id=department_id)

    now = datetime.now(timezone.utc)
    current_interaction.ended_at = now
    current_interaction.outcome = "transferred"
    current_interaction.transfer_to_employee_id = next_employee.employee_id
    
    if current_interaction.started_at:
        start_time = current_interaction.started_at
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        current_interaction.duration_seconds = int((now - start_time).total_seconds())

    next_order = current_interaction.interaction_order + 1
    new_interaction = Interaction(
        journey_id=current_interaction.journey_id,
        employee_id=next_employee.employee_id,
        department_id=department_id,
        interaction_order=next_order,
        started_at=now,
        transfer_from_employee_id=current_interaction.employee_id
    )

    db.add(new_interaction)
    db.commit()
    db.refresh(new_interaction)

    return {
        "transferred": True,
        "new_employee_id": next_employee.employee_id,
        "new_interaction_id": new_interaction.interaction_id
    }
