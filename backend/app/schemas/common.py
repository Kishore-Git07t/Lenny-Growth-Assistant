"""Common Pydantic schemas for structured errors and pagination metadata."""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standardized structured error response model."""

    error: str = Field(..., description="Machine-readable error code", example="not_found")
    message: str = Field(..., description="Human-readable error explanation", example="Session not found")
    status_code: int = Field(..., description="HTTP status code", example=404)
    details: Optional[Dict[str, Any]] = Field(default=None, description="Optional diagnostic details")


class PaginationParams(BaseModel):
    """Standard query parameters for pagination."""

    limit: int = Field(default=20, ge=1, le=100, description="Maximum number of items to return")
    offset: int = Field(default=0, ge=0, description="Number of items to skip")
