"""Pydantic schemas for HTML/CSS artifact generation and persistence."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.retrieval.schemas import CitationSource, IndexCoverage


class ArtifactGenerateRequest(BaseModel):
    """Request payload for generating an HTML/CSS artifact."""

    model_config = ConfigDict(extra="ignore")

    prompt: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="Detailed description or requirements for the HTML/CSS artifact",
        json_schema_extra={"example": "A modern SaaS landing page for an AI growth assistant with hero, features, and pricing"},
    )
    title: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional explicit title for the artifact",
        json_schema_extra={"example": "AI Growth Assistant Landing Page"},
    )
    artifact_type: Optional[str] = Field(
        default="landing_page",
        max_length=64,
        description="Category/type of artifact (e.g. landing_page, dashboard, announcement, component)",
        json_schema_extra={"example": "landing_page"},
    )
    style_preferences: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional style or visual theme preferences (e.g. vibrant, minimalist, enterprise, dark, light)",
        json_schema_extra={"example": "modern minimalist with subtle gradients"},
    )
    include_podcast_context: Optional[bool] = Field(
        default=True,
        description="Whether to search Lenny's Podcast transcripts for relevant growth strategy evidence",
    )
    provider: Optional[str] = Field(
        default=None,
        description="Optional LLM provider override ('ollama', 'google')",
        json_schema_extra={"example": "google"},
    )
    model: Optional[str] = Field(
        default=None,
        description="Optional model identifier override (e.g. 'gemini-2.5-flash', 'qwen2.5:1.5b')",
        json_schema_extra={"example": "gemini-2.5-flash"},
    )


    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        """Ensure prompt is not empty or whitespace-only."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("Prompt cannot be empty or whitespace-only.")
        return stripped

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: Optional[str]) -> Optional[str]:
        """Normalize optional title."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None

    @field_validator("artifact_type")
    @classmethod
    def validate_artifact_type(cls, value: Optional[str]) -> str:
        """Normalize artifact type to lowercase identifier."""
        if not value or not value.strip():
            return "landing_page"
        normalized = value.strip().lower()
        # Keep alphanumeric and underscores
        cleaned = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in normalized)
        return cleaned or "landing_page"

    @field_validator("style_preferences")
    @classmethod
    def validate_style_preferences(cls, value: Optional[str]) -> Optional[str]:
        """Normalize style preferences."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None


class ArtifactResponse(BaseModel):
    """Response payload returned upon generating or retrieving an HTML/CSS artifact."""

    model_config = ConfigDict(from_attributes=True)

    artifact_id: uuid.UUID = Field(..., description="Unique UUID identifier for this artifact message")
    session_id: uuid.UUID = Field(..., description="UUID of the parent conversation session")
    title: str = Field(..., description="Title of the generated artifact")
    artifact_type: str = Field(default="landing_page", description="Artifact category/type identifier")
    prompt: str = Field(..., description="Original user prompt or description")
    html: str = Field(..., description="Sanitized, safe HTML fragment or document body")
    css: str = Field(..., description="Sanitized, safe CSS stylesheet")
    combined_preview: str = Field(..., description="Complete sandboxed HTML document ready for iframe preview")
    status: str = Field(
        ...,
        description="Generation status: 'completed' (successful), 'partial' (fallback applied), or 'failed'",
    )
    provider: str = Field(
        default="ollama",
        description="LLM provider used by Pi Coding Agent (e.g. 'ollama', 'openai')",
    )
    model: Optional[str] = Field(
        default=None,
        description="Model identifier used for generation (e.g. 'qwen2.5:1.5b', 'gpt-4o-mini')",
    )
    created_at: datetime = Field(..., description="UTC timestamp when the artifact was created")

    diagnostics: List[str] = Field(
        default_factory=list,
        description="Security sanitization diagnostics and model generation notes",
    )
    citations: List[CitationSource] = Field(
        default_factory=list,
        description="Verified podcast citations if transcript evidence was incorporated",
    )
    coverage: Optional[IndexCoverage] = Field(
        default=None,
        description="Corpus vector index coverage report if retrieval occurred",
    )
    disclaimer: Optional[str] = Field(
        default=None,
        description="Advisory disclaimer if partial coverage or sanitization interventions occurred",
    )
    is_persisted: bool = Field(
        default=True,
        description="Whether the artifact was successfully persisted in PostgreSQL",
    )

