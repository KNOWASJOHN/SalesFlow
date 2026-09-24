import uuid

from sqlalchemy import Column, String, Numeric, TIMESTAMP, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class Purchase(Base):
    __tablename__ = "purchases"

    purchase_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    journey_id = Column(
        UUID(as_uuid=True),
        ForeignKey("customer_journeys.journey_id", ondelete="CASCADE"),
        nullable=False,
        unique=True
    )

    customer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("customers.customer_id"),
        nullable=False
    )

    product_category = Column(
        String(100),
        nullable=False
    )

    amount = Column(
        Numeric(12, 2),
        nullable=False
    )

    purchased_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now()
    )