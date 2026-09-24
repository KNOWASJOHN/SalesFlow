import uuid
from sqlalchemy import Column, String, Boolean, Numeric, TIMESTAMP, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
from sqlalchemy.orm import relationship

class Journey(Base):
    __tablename__ = "customer_journeys"
    interactions = relationship("Interaction", order_by="Interaction.interaction_order", lazy="joined")
    journey_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.customer_id"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.campaign_id"), nullable=True)
    status = Column(String(20), nullable=False, default="active")  # active | completed | abandoned
    purchased = Column(Boolean, nullable=False, default=False)
    started_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    ended_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())