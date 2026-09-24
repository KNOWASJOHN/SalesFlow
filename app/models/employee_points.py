import uuid
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base

class EmployeePoint(Base):
    __tablename__ = "employee_points"

    point_entry_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    journey_id = Column(UUID(as_uuid=True), ForeignKey("customer_journeys.journey_id", ondelete="CASCADE"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.employee_id"), nullable=False)
    points = Column(Integer, nullable=False)
    reason = Column(String(150), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        CheckConstraint('points <> 0', name='employee_points_ck'),
    )

    journey = relationship("Journey")
    employee = relationship("Employee")
