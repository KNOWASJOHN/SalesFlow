import uuid
from sqlalchemy import Column, String, TIMESTAMP, ForeignKey, CheckConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class AdEvent(Base):
    __tablename__ = "ad_events"

    ad_event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.campaign_id"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.customer_id"), nullable=True)
    event_type = Column(String(30), nullable=False)  # impression | click | landing | lead
    event_time = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    session_reference = Column(String(100), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('impression', 'click', 'landing', 'lead')",
            name="ad_events_type_ck",
        ),
    )