"""
Shared pagination for the list endpoints.

Every list route takes the same two query parameters and applies them to a
SQLAlchemy query, so a table with thousands of rows can never dump itself into
one dashboard response. Filtering stays in the router; only the window moves
here.
"""

from dataclasses import dataclass

from fastapi import Query

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass(frozen=True)
class PageParams:
    """One page of a list result: how many rows, and from where."""

    limit: int
    offset: int

    def apply(self, query):
        """Return ``query`` limited to this page."""
        return query.limit(self.limit).offset(self.offset)


def page_params(
    limit: int = Query(
        DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description="Maximum number of rows to return.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Number of rows to skip before the first returned row.",
    ),
) -> PageParams:
    """FastAPI dependency producing the page window for a list endpoint."""
    return PageParams(limit=limit, offset=offset)
