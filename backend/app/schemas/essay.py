"""Pydantic schemas for Ship 30 for 30 essay generation and artifact persistence."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.retrieval.schemas import CitationSource, IndexCoverage


class EssayGenerateRequest(BaseModel):
    """Request payload for generating a Ship 30 for 30 essay."""

    topic: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="The topic or question from Lenny's Podcast to transform into an essay",
        example="When founders should hire their first salespeople according to Jason Lemkin",
    )
    audience: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Target reader persona for the essay (e.g. 'Early-stage SaaS founders')",
        example="Early-stage SaaS founders",
    )
    target_word_count: Optional[int] = Field(
        default=1250,
        ge=500,
        le=2500,
        description="Target word count for the complete essay (default 1,250 words)",
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


    @field_validator("topic")
    @classmethod
    def validate_topic_non_empty(cls, value: str) -> str:
        """Ensure topic is not empty or whitespace-only."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("Topic cannot be empty or whitespace-only.")
        return stripped

    @field_validator("audience")
    @classmethod
    def validate_audience(cls, value: Optional[str]) -> Optional[str]:
        """Normalize audience if provided."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None


class EssaySectionPlan(BaseModel):
    """Structural plan for an individual section of the essay."""

    section_index: int = Field(..., description="1-based index of the section")
    heading: str = Field(..., description="Actionable H2 heading")
    purpose: str = Field(..., description="Core argument or takeaway of this section")
    target_words: int = Field(default=250, description="Word budget target for this section")
    key_points: List[str] = Field(default_factory=list, description="Key bullet points to cover")
    evidence_indices: List[int] = Field(default_factory=list, description="Citation indices to reference")


class EssayOutline(BaseModel):
    """Structured outline generated in Stage 1 of essay orchestration."""

    title: str = Field(..., description="Clear, benefit-driven headline for the target reader")
    audience: str = Field(..., description="Explicit target reader")
    hook: str = Field(..., description="Opening tension or compelling question")
    core_thesis: str = Field(..., description="Central thesis statement grounded in evidence")
    sections: List[EssaySectionPlan] = Field(default_factory=list, description="List of planned sections")
    closing_takeaway: str = Field(..., description="Single actionable closing takeaway")


class EssayResponse(BaseModel):
    """Response payload returned upon generating a Ship 30 for 30 essay artifact."""

    session_id: uuid.UUID = Field(..., description="UUID of the parent chat session")
    message_id: Optional[uuid.UUID] = Field(None, description="UUID of the persisted assistant message")
    artifact_type: str = Field(default="ship30_essay", description="Artifact type identifier")
    title: str = Field(..., description="Headline of the generated essay")
    topic: str = Field(..., description="Original request topic")
    audience: str = Field(..., description="Target reader persona")
    content: str = Field(..., description="Complete Markdown content of the essay")
    word_count: int = Field(..., description="Actual measured word count of the essay")
    target_word_count: int = Field(default=1250, description="Nominal target word count")
    status: str = Field(
        ...,
        description="Generation outcome: 'completed' (within 1,100-1,400 words), 'partial', or 'insufficient_evidence'",
    )
    provider: str = Field(..., description="LLM provider used by Pi Coding Agent")
    model: str = Field(..., description="LLM model identifier used for generation")
    citations: List[CitationSource] = Field(
        default_factory=list,
        description="Structured verified source citations supporting the essay",
    )
    coverage: Optional[IndexCoverage] = Field(
        default=None,
        description="Corpus vector index coverage statistics",
    )
    disclaimer: Optional[str] = Field(
        default=None,
        description="Advisory note if search is evaluated against a partial index",
    )
    created_at: datetime = Field(..., description="UTC creation timestamp")

    model_config = ConfigDict(from_attributes=True)
