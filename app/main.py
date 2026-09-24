from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Dict, Any
from app.routers import customers, campaigns, journeys, departments, interactions, purchases, feedback, points

from .core.database import get_db

app = FastAPI(title="Sales Interaction Tracking and Analytics System")

app.include_router(customers.router)
app.include_router(campaigns.router)
app.include_router(journeys.router)
app.include_router(departments.router)
app.include_router(interactions.router)
app.include_router(purchases.router)
app.include_router(feedback.router)
app.include_router(points.router)

@app.get("/health")
def health_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        # Execute a trivial query against the database
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        # If DB is unreachable, return a clear error response (not a raw traceback)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "error", "database": "disconnected", "message": str(e)}
        )
