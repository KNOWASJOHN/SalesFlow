from sqlalchemy import Column, String, Boolean, TIMESTAMP, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
import uuid


class Employee(Base):
    __tablename__ = "employees"

    employee_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    employee_code = Column(
        String(30),
        nullable=False,
        unique=True
    )

    name = Column(
        String(120),
        nullable=False
    )

    role = Column(
        String(80),
        nullable=False
    )

    department_id = Column(
        UUID(as_uuid=True),
        ForeignKey("departments.department_id"),
        nullable=False
    )

    is_online = Column(
        Boolean,
        nullable=False,
        default=False
    )

    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now()
    )