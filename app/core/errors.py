"""
Global exception handlers for the Sales Interaction Tracking API.

All errors must reach the client as:
  { "error": "ERROR_CODE", "message": "Human-readable description." }

Status code mapping:
  400 - Bad request / validation failure
  404 - Resource not found
  409 - Invalid state transition / conflict
  422 - Unprocessable entity (FastAPI default for validation — overridden to 400)
  500 - Unexpected server-side error
"""

import logging
import traceback

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _error_response(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "message": message},
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    Catch all HTTPException / HTTPException subclasses raised by FastAPI or our
    own routers.  If the detail is already a dict with "error" + "message" keys
    we pass it through unchanged; otherwise we normalise it.
    """
    detail = exc.detail

    if isinstance(detail, dict) and "error" in detail and "message" in detail:
        # Already in the correct shape — just wrap in JSONResponse.
        return JSONResponse(status_code=exc.status_code, content=detail)

    # Normalise plain strings / other shapes.
    error_code = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        500: "INTERNAL_SERVER_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }.get(exc.status_code, "HTTP_ERROR")

    message = str(detail) if detail else f"HTTP {exc.status_code}"
    return _error_response(exc.status_code, error_code, message)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    FastAPI raises RequestValidationError (422 by default) when a Pydantic schema
    fails.  We re-map this to 400 and surface the first validation message.
    """
    errors = exc.errors()
    if errors:
        first = errors[0]
        loc = " -> ".join(str(l) for l in first.get("loc", []) if l != "body")
        msg = first.get("msg", "Validation error")
        message = f"{loc}: {msg}" if loc else msg
    else:
        message = "Invalid request payload."

    return _error_response(
        status.HTTP_400_BAD_REQUEST,
        "VALIDATION_ERROR",
        message,
    )


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """
    Catch unhandled SQLAlchemy IntegrityError (unique constraint, FK violation, etc.)
    that slipped past the router-level checks.
    """
    logger.warning("Unhandled IntegrityError: %s", exc.orig)
    return _error_response(
        status.HTTP_409_CONFLICT,
        "INTEGRITY_ERROR",
        "The request conflicts with existing data or violates a database constraint.",
    )


async def operational_error_handler(request: Request, exc: OperationalError) -> JSONResponse:
    """
    Database connection / query execution failures.
    """
    logger.error("Database operational error: %s", exc.orig)
    return _error_response(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "DATABASE_ERROR",
        "A database error occurred. Please try again later.",
    )


async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """
    Catch-all for any remaining SQLAlchemy errors not caught above.
    """
    logger.error("Unhandled SQLAlchemy error: %s", exc)
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "DATABASE_ERROR",
        "An unexpected database error occurred.",
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Last-resort handler: catch any Python exception that wasn't handled above.
    Logs the full traceback server-side but never exposes it to the client.
    """
    logger.error(
        "Unhandled exception on %s %s:\n%s",
        request.method,
        request.url.path,
        traceback.format_exc(),
    )
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_SERVER_ERROR",
        "An unexpected error occurred. Please contact support if this persists.",
    )
