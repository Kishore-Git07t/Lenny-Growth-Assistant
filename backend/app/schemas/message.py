"""Pydantic schemas for conversational messages."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MessageCreate(BaseModel):
    """Schema for submitting a message in an existing conversation.

    Note: The role is deliberately omitted because all externally submitted
    messages are strictly enforced by the backend as 'user' role to prevent
    impersonation attacks.
    """

    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The content of the message",
        example="What does Elena Verna recommend for B2B freemium vs free trial models?",
    )

    @field_validator("content")
    @classmethod
    def validate_content_non_empty(cls, value: str) -> str:
        """Validate that message content is not empty or whitespace-only."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("Message content cannot be empty or whitespace-only.")
        return stripped


class MessageResponse(BaseModel):
    """Schema representing a persistent chat message."""

    id: uuid.UUID = Field(..., description="Unique UUID identifier of the message")
    session_id: uuid.UUID = Field(..., description="UUID of the parent chat session")
    role: str = Field(..., description="Message role (e.g. 'user', 'assistant')")
    content: str = Field(..., description="Message text content")
    source_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional grounding citations or source transcript metadata",
    )
    created_at: datetime = Field(..., description="UTC creation timestamp")

    model_config = ConfigDict(from_attributes=True)


class MessageListResponse(BaseModel):
    """Schema for paginated message history list."""

    items: List[MessageResponse] = Field(..., description="Chronological list of messages")
    total: int = Field(..., description="Total message count in this session")
    limit: int = Field(..., description="Pagination limit")
    offset: int = Field(..., description="Pagination offset")
