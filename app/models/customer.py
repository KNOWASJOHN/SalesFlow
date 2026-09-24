from sqlalchemy import Column, String, Boolean, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
import uuid


class Customer(Base):
    __tablename__ = "customers"

    customer_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    contact_number = Column(
        String(30),
        nullable=False,
        unique=True
    )

    age_group = Column(
        String(30),
        nullable=True
    )

    occupation = Column(
        String(100),
        nullable=True
    )

    location_type = Column(
        String(50),
        nullable=True
    )

    budget_range = Column(
        String(50),
        nullable=True
    )

    interested_category = Column(
        String(100),
        nullable=True
    )

    purchase_intent = Column(
        String(30),
        nullable=True
    )

    previous_customer = Column(
        Boolean,
        nullable=False,
        default=False
    )

    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now()
    )