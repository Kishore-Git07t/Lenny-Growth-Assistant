"""Schemas for safe LLM provider capability and configuration metadata."""

from typing import List, Optional
from pydantic import BaseModel, Field


class ProviderInfo(BaseModel):
    """Safe, non-sensitive capability metadata for an individual LLM provider."""

    id: str = Field(..., description="Provider identifier (e.g. 'ollama', 'google')")
    name: str = Field(..., description="Display name for UI selector")
    model: str = Field(..., description="Configured model identifier")
    type: str = Field(..., description="'local' or 'cloud'")
    is_configured: bool = Field(..., description="Whether required credentials exist in server environment")
    description: str = Field(..., description="Help text or advisory note")


class ProviderStatusResponse(BaseModel):
    """Response returned by GET /api/models and GET /api/providers."""

    default_provider: str = Field(..., description="Server default provider setting")
    active_provider: str = Field(..., description="Currently active server default provider")
    providers: List[ProviderInfo] = Field(..., description="List of supported providers and configuration status")
