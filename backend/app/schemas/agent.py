from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.retrieval.schemas import CitationSource, IndexCoverage
from backend.app.schemas.message import MessageResponse


class AgentRespondRequest(BaseModel):
    """Request payload for triggering an assistant response within a session."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The content of the user prompt/question",
        example="What frameworks are most effective for improving B2B SaaS onboarding retention?",
    )
    provider: Optional[str] = Field(
        default=None,
        description="Optional LLM provider override ('ollama', 'google')",
        example="google",
    )
    model: Optional[str] = Field(
        default=None,
        description="Optional model identifier override (e.g. 'gemini-2.5-flash', 'qwen2.5:1.5b')",
        example="gemini-2.5-flash",
    )

    @field_validator("content")
    @classmethod
    def validate_content_non_empty(cls, value: str) -> str:
        """Validate that message content is not empty or whitespace-only."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("Message content cannot be empty or whitespace-only.")
        return stripped



class AgentRespondResponse(BaseModel):
    """Response payload returned upon successfully generating and persisting an assistant message."""

    session_id: uuid.UUID = Field(..., description="UUID of the parent chat session")
    user_message: MessageResponse = Field(..., description="The persisted user message record")
    assistant_message: MessageResponse = Field(..., description="The persisted assistant response record")
    provider: str = Field(..., description="Active LLM provider used by Pi Coding Agent (e.g. 'ollama', 'openai')")
    model: str = Field(..., description="Model identifier used for generation (e.g. 'qwen2.5:1.5b')")
    retried: bool = Field(default=False, description="Whether this invocation re-used an existing uncompleted user message on retry")

    # Grounded RAG citation metadata (Phase 3.2C-2)
    citations: List[CitationSource] = Field(
        default_factory=list,
        description="Structured, verified source citations supporting the assistant answer",
    )
    retrieval_status: Optional[str] = Field(
        default=None,
        description="Outcome of vector retrieval ('success', 'insufficient_evidence', 'no_indexed_content')",
    )
    coverage: Optional[IndexCoverage] = Field(
        default=None,
        description="Corpus vector index coverage statistics",
    )
    disclaimer: Optional[str] = Field(
        default=None,
        description="Advisory note if search is evaluated against a partial index",
    )

    model_config = ConfigDict(from_attributes=True)

