"""
Analytics aggregation endpoints.

These exist so the dashboard's Overview and Basic Analytics pages stop
computing their numbers on the client: every value here is a query against the
same tables the write paths fill.

All routes are read-only and repeatable — calling one twice changes nothing, so
the dashboard can poll them freely.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.analytics import (
    CampaignFunnel,
    DepartmentRatingSummary,
    EmployeePerformance,
    EmployeeRatingSummary,
    LeaderboardEntry,
    OverviewMetrics,
    TransferPath,
)
from app.services import analytics_service, calls_service

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/feedback/by-department", response_model=List[DepartmentRatingSummary])
def feedback_by_department(db: Session = Depends(get_db)):
    """
    Average customer/department/employee rating per department.

    Only departments that actually have attributed feedback appear; a department
    with none is absent rather than reported as zero-rated.
    """
    return analytics_service.feedback_by_department(db)


@router.get("/feedback/by-employee", response_model=List[EmployeeRatingSummary])
def feedback_by_employee(db: Session = Depends(get_db)):
    """Average customer/department/employee rating per employee."""
    return analytics_service.feedback_by_employee(db)


@router.get("/overview", response_model=OverviewMetrics)
def overview(db: Session = Depends(get_db)):
    """
    Headline numbers for the Overview page: who is online, what is happening on
    the phones right now, and what today has sold and awarded.
    """
    return analytics_service.overview(
        db,
        active_calls=calls_service.count_active_calls(),
    )


@router.get("/transfers", response_model=List[TransferPath])
def transfer_paths(db: Session = Depends(get_db)):
    """Transfer counts per (from department, to department) pair."""
    return analytics_service.transfer_paths(db)


@router.get("/employees/leaderboard", response_model=List[LeaderboardEntry])
def employee_leaderboard(db: Session = Depends(get_db)):
    """Every employee by total points, highest first, with rank."""
    return analytics_service.employee_leaderboard(db)


@router.get("/employees/{employee_id}/performance", response_model=EmployeePerformance)
def employee_performance(employee_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Points, interaction count and conversion rate for one employee.

    ``conversion_rate`` is a fraction (0.25 = one purchase per four journeys
    touched), not a percentage.
    """
    performance = analytics_service.employee_performance(db, employee_id)

    if performance is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "EMPLOYEE_NOT_FOUND",
                "message": "No employee with this ID exists.",
            },
        )

    return performance


@router.get("/campaigns/{campaign_id}/funnel", response_model=CampaignFunnel)
def campaign_funnel(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Ad events, journeys and purchases for one campaign.

    Stages are independent counts, so they only read as a funnel when the events
    were recorded in order — the schema does not enforce impression -> click ->
    journey -> purchase.
    """
    funnel = analytics_service.campaign_funnel(db, campaign_id)

    if funnel is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "CAMPAIGN_NOT_FOUND",
                "message": "No campaign with this ID exists.",
            },
        )

    return funnel
