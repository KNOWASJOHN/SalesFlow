"""
Response schemas for the analytics aggregation endpoints.

Every one of these is a computed row, never a stored table: the dictionary the
mock dashboard used to invent is now the query result.
"""

import uuid
from typing import Optional

from pydantic import BaseModel


class DepartmentRatingSummary(BaseModel):
    """Average feedback ratings for one department."""

    department_id: uuid.UUID
    department_name: Optional[str] = None
    feedback_count: int
    average_overall_rating: Optional[float] = None
    average_department_rating: Optional[float] = None
    average_employee_rating: Optional[float] = None


class EmployeeRatingSummary(BaseModel):
    """Average feedback ratings for one employee."""

    employee_id: uuid.UUID
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None
    department_id: Optional[uuid.UUID] = None
    feedback_count: int
    average_overall_rating: Optional[float] = None
    average_department_rating: Optional[float] = None
    average_employee_rating: Optional[float] = None


class OverviewMetrics(BaseModel):
    """The headline numbers on the dashboard's Overview page."""

    active_employees: int
    active_calls: int
    purchases_today: int
    revenue_today: float
    points_awarded_today: int


class CampaignFunnel(BaseModel):
    """
    A campaign's funnel.

    The stages are independent counts, not a filtered cascade: nothing in the
    schema requires a click to precede a journey, so the numbers are reported
    as observed and are only monotonic when the data was recorded in order.
    """

    campaign_id: uuid.UUID
    campaign_name: Optional[str] = None
    impressions: int
    clicks: int
    landings: int
    leads: int
    journeys: int
    purchases: int


class LeaderboardEntry(BaseModel):
    """One employee's standing on the points leaderboard."""

    rank: int
    employee_id: uuid.UUID
    employee_code: str
    employee_name: str
    department_id: uuid.UUID
    total_points: int


class EmployeePerformance(BaseModel):
    """One employee's contribution numbers."""

    employee_id: uuid.UUID
    employee_code: str
    employee_name: str
    department_id: uuid.UUID
    total_points: int
    interaction_count: int
    journeys_touched: int
    journeys_purchased: int
    conversion_rate: float


class TransferPath(BaseModel):
    """How often customers move from one department to another."""

    from_department_id: uuid.UUID
    from_department_name: Optional[str] = None
    to_department_id: uuid.UUID
    to_department_name: Optional[str] = None
    transfer_count: int
