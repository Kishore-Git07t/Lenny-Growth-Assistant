"""Semantic retrieval service combining query embedding, pgvector similarity search, and source citations."""

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.embeddings.client import (
    OllamaEmbeddingClient,
)
from backend.app.repositories.embedding_repository import (
    get_index_coverage,
    semantic_search,
)
from backend.app.retrieval.citations import (
    build_timestamped_youtube_url,
    format_seconds_to_timestamp,
)
from backend.app.retrieval.schemas import (
    CitationSource,
    IndexCoverage,
    RetrievalResponse,
)

logger = logging.getLogger(__name__)

DEFAULT_TOP_K: int = 5
MAX_TOP_K: int = 10
MIN_TOP_K: int = 1


class SemanticRetrievalService:
    """Service for grounded semantic vector search across podcast transcript passages."""

    def __init__(
        self,
        db: Session,
        client: Optional[OllamaEmbeddingClient] = None,
        model: Optional[str] = None,
    ):
        self.db = db
        settings = get_settings()

        self.model = model or settings.embedding_model
        self.client = client or OllamaEmbeddingClient(
            base_url=settings.ollama_base_url,
            model=self.model,
            dimensions=settings.embedding_dimensions,
            timeout_seconds=float(settings.embedding_timeout_seconds),
            max_retries=settings.embedding_max_retries,
        )

    def retrieve(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
    ) -> RetrievalResponse:
        """Perform semantic retrieval for a user question.

        Workflow:
            1. Validate query string (reject empty/whitespace).
            2. Check index coverage to report partial corpus indexing honestly.
            3. Generate 768-D query embedding using Ollama ('search_query: ' prefix).
            4. Execute nearest-neighbor vector similarity search with joins.
            5. Construct verifiable timestamped source citations.
            6. Return structured RetrievalResponse.

        Args:
            query: User search question or keyword query.
            top_k: Number of passages to retrieve (bounded 1 to 10, default 5).

        Returns:
            RetrievalResponse with grounded passages, citations, and coverage details.

        Raises:
            ValueError: If query is empty or whitespace-only.
            EmbeddingError: If Ollama fails to embed the query.
        """
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty or whitespace-only.")

        cleaned_query = query.strip()
        bounded_top_k = max(MIN_TOP_K, min(MAX_TOP_K, top_k))

        # 1. Inspect live corpus index coverage
        raw_cov = get_index_coverage(self.db, model_name=self.model)

        total_eps = raw_cov["total_episodes"]
        idx_eps = raw_cov["indexed_episodes"]
        total_chunks = raw_cov["total_chunks"]
        idx_chunks = raw_cov["indexed_chunks"]
        is_partial = raw_cov["is_partial"]

        if is_partial:
            cov_desc = (
                f"Partial index: {idx_chunks} of {total_chunks} chunks indexed "
                f"across {idx_eps} of {total_eps} episodes."
            )
        else:
            cov_desc = f"Full index: All {total_chunks} chunks across {total_eps} episodes are indexed."

        coverage_info = IndexCoverage(
            total_episodes=total_eps,
            indexed_episodes=idx_eps,
            total_chunks=total_chunks,
            indexed_chunks=idx_chunks,
            model_name=self.model,
            is_partial=is_partial,
            description=cov_desc,
        )

        # 2. Handle empty index scenario
        if idx_chunks == 0:
            logger.info("Semantic retrieval aborted: vector index is empty for model '%s'.", self.model)
            return RetrievalResponse(
                query=cleaned_query,
                status="no_indexed_content",
                items=[],
                coverage=coverage_info,
                disclaimer=(
                    f"No vector embeddings exist in the database for model '{self.model}'. "
                    "Please run the embedding pipeline first."
                ),
            )

        # 3. Generate 768-D query embedding via Ollama
        query_vector = self.client.embed_query(cleaned_query)

        # 4. Perform vector similarity search
        search_results = semantic_search(
            db=self.db,
            query_vector=query_vector,
            top_k=bounded_top_k,
            model_name=self.model,
        )

        # 5. Build grounded source citations
        citation_items: List[CitationSource] = []

        for chunk, episode, distance in search_results:
            c_dist = round(distance, 4)
            sim_score = round(max(0.0, min(1.0, 1.0 - distance)), 4)
            ts_label = format_seconds_to_timestamp(chunk.start_seconds)
            ts_url = build_timestamped_youtube_url(
                youtube_url=episode.youtube_url,
                video_id=episode.video_id,
                start_seconds=chunk.start_seconds,
            )

            citation = CitationSource(
                episode_id=episode.id,
                episode_title=episode.title,
                episode_slug=episode.slug,
                guest_name=episode.guest_name,
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                start_seconds=chunk.start_seconds,
                end_seconds=chunk.end_seconds,
                timestamp_label=ts_label,
                youtube_url=episode.youtube_url,
                timestamped_url=ts_url,
                cosine_distance=c_dist,
                similarity_score=sim_score,
            )
            citation_items.append(citation)

        # 6. Determine status and partial index disclaimer
        if not citation_items:
            status = "insufficient_evidence"
        else:
            status = "success"

        disclaimer: Optional[str] = None
        if is_partial:
            disclaimer = (
                f"Note: Search evaluated against {idx_chunks} indexed passages across "
                f"{idx_eps} episodes out of {total_eps} total podcast episodes in the corpus. "
                "Unindexed episodes were not searched."
            )

        logger.info(
            "Semantic retrieval completed for query (length %d): %d items returned (status=%s, top_k=%d).",
            len(cleaned_query),
            len(citation_items),
            status,
            bounded_top_k,
        )

        return RetrievalResponse(
            query=cleaned_query,
            status=status,
            items=citation_items,
            coverage=coverage_info,
            disclaimer=disclaimer,
        )
