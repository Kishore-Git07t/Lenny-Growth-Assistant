"""Pydantic schemas for semantic retrieval and verifiable source citations."""

from typing import List, Optional
import uuid

from pydantic import BaseModel, Field, field_validator


class CitationSource(BaseModel):
    """Grounded source citation with verbatim excerpt, metadata and timestamped links."""

    episode_id: uuid.UUID = Field(..., description="UUID of the parent podcast episode.")
    episode_title: str = Field(..., description="Title of the podcast episode.")
    episode_slug: str = Field(..., description="URL slug of the episode.")
    guest_name: Optional[str] = Field(None, description="Guest name if identified.")
    chunk_id: uuid.UUID = Field(..., description="UUID of the retrieved transcript chunk.")
    chunk_index: int = Field(..., description="Zero-based index of the chunk within the episode.")
    content: str = Field(..., description="Exact verbatim transcript excerpt from the chunk.")
    char_start: Optional[int] = Field(None, description="Character offset start in the full transcript.")
    char_end: Optional[int] = Field(None, description="Character offset end in the full transcript.")
    start_seconds: Optional[float] = Field(None, description="Passage start timestamp in seconds.")
    end_seconds: Optional[float] = Field(None, description="Passage end timestamp in seconds.")
    timestamp_label: Optional[str] = Field(None, description="Human-readable timestamp string (e.g. '01:05').")
    youtube_url: Optional[str] = Field(None, description="Base episode YouTube URL.")
    timestamped_url: Optional[str] = Field(None, description="Direct timestamped YouTube link.")
    cosine_distance: float = Field(..., description="Cosine distance from query vector (0.0 = identical).")
    similarity_score: float = Field(..., description="Interpretable similarity score (1.0 - distance, bounded [0, 1]).")


class IndexCoverage(BaseModel):
    """Metadata describing the proportion of the podcast corpus currently indexed in the vector store."""

    total_episodes: int = Field(..., description="Total podcast episodes in the database.")
    indexed_episodes: int = Field(..., description="Number of episodes with at least one vector embedding.")
    total_chunks: int = Field(..., description="Total transcript chunks in the database.")
    indexed_chunks: int = Field(..., description="Number of chunks currently with vector embeddings.")
    model_name: str = Field(..., description="Embedding model identifier.")
    is_partial: bool = Field(..., description="True if only a subset of the corpus is currently indexed.")
    description: str = Field(..., description="Human-readable explanation of index coverage.")


class RetrievalRequest(BaseModel):
    """Request payload for semantic retrieval."""

    query: str = Field(..., min_length=1, description="User search query or question.")
    top_k: int = Field(default=5, ge=1, le=10, description="Number of passages to retrieve (1 to 10).")
    model: Optional[str] = Field(None, description="Optional override for embedding model.")

    @field_validator("query")
    @classmethod
    def validate_non_whitespace(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Query cannot be empty or whitespace-only.")
        return trimmed


class RetrievalResponse(BaseModel):
    """Structured response containing semantic search results and honest corpus coverage."""

    query: str = Field(..., description="Cleaned search query.")
    status: str = Field(..., description="Retrieval outcome ('success', 'insufficient_evidence', 'no_indexed_content').")
    items: List[CitationSource] = Field(default_factory=list, description="Top ranked grounded source passages.")
    coverage: IndexCoverage = Field(..., description="Index coverage report.")
    disclaimer: Optional[str] = Field(None, description="Advisory note if search is evaluated against a partial index.")
