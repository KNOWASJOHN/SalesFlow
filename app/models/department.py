from sqlalchemy import Column, String, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
import uuid


class Department(Base):
    __tablename__ = "departments"

    department_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    name = Column(
        String(100),
        nullable=False,
        unique=True
    )

    description = Column(
        Text,
        nullable=True
    )

    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now()
    )