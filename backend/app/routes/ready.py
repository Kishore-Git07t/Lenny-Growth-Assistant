"""Readiness probe endpoint checking database connectivity."""

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Response, status

from backend.app.database import check_db_connectivity

router = APIRouter(tags=["Health"])


@router.get(
    "/api/ready",
    summary="Readiness check probing database connectivity",
    responses={
        200: {"description": "Service is ready to handle requests"},
        503: {"description": "Service is not ready (database unconfigured or unavailable)"},
    },
)
def get_readiness(response: Response) -> Dict[str, Any]:
    """Check whether the service and its required dependencies (PostgreSQL) are operational.

    Returns:
        HTTP 200 if connected to the database.
        HTTP 503 if the database is unconfigured or unavailable.
    """
    is_connected, detail = check_db_connectivity()
    utc_now = datetime.now(timezone.utc).isoformat()

    if is_connected:
        return {
            "status": "ready",
            "database": "connected",
            "timestamp": utc_now,
        }

    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    if detail == "unconfigured":
        return {
            "status": "not_ready",
            "database": "unconfigured",
            "detail": "DATABASE_URL is not configured in environment.",
            "timestamp": utc_now,
        }

    return {
        "status": "not_ready",
        "database": "unavailable",
        "detail": detail,
        "timestamp": utc_now,
    }
