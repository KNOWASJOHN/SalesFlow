import logging

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from typing import Dict, Any

from app.routers import customers, campaigns, journeys, departments, interactions, purchases, feedback, points
from app.core.errors import (
    http_exception_handler,
    validation_exception_handler,
    integrity_error_handler,
    operational_error_handler,
    sqlalchemy_error_handler,
    unhandled_exception_handler,
)
from .core.database import get_db

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Sales Interaction Tracking and Analytics System",
    description="Backend API for tracking customer journeys, interactions, purchases, feedback and employee points.",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Exception handlers  (most-specific first)
# ---------------------------------------------------------------------------
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(IntegrityError, integrity_error_handler)
app.add_exception_handler(OperationalError, operational_error_handler)
app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(customers.router)
app.include_router(campaigns.router)
app.include_router(journeys.router)
app.include_router(departments.router)
app.include_router(interactions.router)
app.include_router(purchases.router)
app.include_router(feedback.router)
app.include_router(points.router)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"])
def health_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "error", "database": "disconnected", "message": str(e)},
        )
