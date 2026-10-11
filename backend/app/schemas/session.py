"""Pydantic schemas for chat sessions."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionCreate(BaseModel):
    """Schema for creating a new conversation session."""

    title: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional human-readable title for the session",
        example="PLG and Retention Loops",
    )
    user_metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Safe custom metadata associated with the session",
        example={"topic": "growth", "client": "web"},
    )

    @field_validator("user_metadata")
    @classmethod
    def validate_metadata(cls, value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Ensure user metadata is bounded in size to prevent storage abuse."""
        if value is None:
            return {}
        if len(value) > 50:
            raise ValueError("user_metadata cannot exceed 50 top-level keys")
        return value


class SessionUpdate(BaseModel):
    """Schema for updating an existing conversation session."""

    title: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Updated human-readable title for the session",
        example="When to hire sales according to Jason Lemkin",
    )
    user_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional updated user metadata for the session",
        example={"topic": "growth", "client": "web"},
    )

    @field_validator("title")
    @classmethod
    def validate_title_non_empty(cls, value: Optional[str]) -> Optional[str]:
        """Validate title is non-empty and bounded."""
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Session title cannot be empty or whitespace-only.")
        if len(stripped) > 255:
            return stripped[:255]
        return stripped

    @field_validator("user_metadata")
    @classmethod
    def validate_metadata(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Ensure updated user metadata is bounded."""
        if value is None:
            return None
        if len(value) > 50:
            raise ValueError("user_metadata cannot exceed 50 top-level keys")
        return value


class SessionResponse(BaseModel):
    """Schema representing a persistent chat session."""

    id: uuid.UUID = Field(..., description="Unique UUID identifier of the session")
    title: Optional[str] = Field(default=None, description="Title of the session")
    user_metadata: Dict[str, Any] = Field(default_factory=dict, description="Session metadata")
    created_at: datetime = Field(..., description="UTC creation timestamp")
    updated_at: datetime = Field(..., description="UTC last updated timestamp")

    model_config = ConfigDict(from_attributes=True)


class SessionListResponse(BaseModel):
    """Schema for paginated session list."""

    items: List[SessionResponse] = Field(..., description="List of sessions")
    total: int = Field(..., description="Total number of matching sessions")
    limit: int = Field(..., description="Pagination limit")
    offset: int = Field(..., description="Pagination offset")
