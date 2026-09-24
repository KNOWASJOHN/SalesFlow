import uuid
from sqlalchemy import Column, Integer, TIMESTAMP, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class Interaction(Base):
    __tablename__ = "interactions"

    interaction_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    journey_id = Column(UUID(as_uuid=True), ForeignKey("customer_journeys.journey_id"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.employee_id"), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.department_id"), nullable=False)
    interaction_order = Column(Integer, nullable=False)
    started_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    ended_at = Column(TIMESTAMP(timezone=True), nullable=True)