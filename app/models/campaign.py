from sqlalchemy import Column, String, TIMESTAMP, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
import uuid


class Campaign(Base):
    __tablename__ = "campaigns"

    campaign_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    campaign_code = Column(
        String(40),
        nullable=False,
        unique=True
    )

    name = Column(
        String(150),
        nullable=False
    )

    department_id = Column(
        UUID(as_uuid=True),
        ForeignKey("departments.department_id"),
        nullable=True
    )

    campaign_team = Column(
        String(120),
        nullable=False
    )

    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now()
    )