import uuid

from sqlalchemy import (
    Column,
    String,
    Text,
    SmallInteger,
    TIMESTAMP,
    ForeignKey,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class Feedback(Base):
    __tablename__ = "feedback"

    feedback_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    journey_id = Column(
        UUID(as_uuid=True),
        ForeignKey("customer_journeys.journey_id", ondelete="CASCADE"),
        nullable=False
    )

    customer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("customers.customer_id"),
        nullable=False
    )

    feedback_type = Column(
        String(20),
        nullable=False
    )

    employee_id = Column(
        UUID(as_uuid=True),
        ForeignKey("employees.employee_id"),
        nullable=True
    )

    department_id = Column(
        UUID(as_uuid=True),
        ForeignKey("departments.department_id"),
        nullable=True
    )

    overall_rating = Column(
        SmallInteger,
        nullable=True
    )

    employee_rating = Column(
        SmallInteger,
        nullable=True
    )

    department_rating = Column(
        SmallInteger,
        nullable=True
    )

    reason_for_not_purchasing = Column(
        Text,
        nullable=True
    )

    product_interest = Column(
        String(100),
        nullable=True
    )

    price_concern = Column(
        Text,
        nullable=True
    )

    competitor_preference = Column(
        Text,
        nullable=True
    )

    general_feedback = Column(
        Text,
        nullable=True
    )

    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now()
    )