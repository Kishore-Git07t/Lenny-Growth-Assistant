"""Automated unit and integration tests for semantic retrieval and source citations (Phase 3.2C-1)."""

from contextlib import contextmanager
from datetime import date
import math
from typing import Any, List
import uuid
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy.orm import Session

from backend.app.database import (
    DatabaseUnavailableException,
    DatabaseUnconfiguredException,
)
from backend.app.embeddings.client import (
    DEFAULT_DOC_PREFIX,
    DEFAULT_QUERY_PREFIX,
    EXPECTED_EMBEDDING_DIMENSIONS,
    EmbeddingError,
    OllamaEmbeddingClient,
    OllamaTimeoutError,
)
from backend.app.models.chunk import TranscriptChunk
from backend.app.models.embedding import TranscriptEmbedding
from backend.app.models.episode import PodcastEpisode
from backend.app.repositories.chunk_repository import count_chunks, create_chunks
from backend.app.repositories.embedding_repository import (
    count_embeddings,
    create_or_update_embedding,
    get_index_coverage,
    semantic_search,
)
from backend.app.repositories.episode_repository import count_episodes, create_episode
import backend.app.retrieval.cli as cli
from backend.app.retrieval.citations import (
    build_timestamped_youtube_url,
    format_seconds_to_timestamp,
)
from backend.app.retrieval.schemas import (
    CitationSource,
    IndexCoverage,
    RetrievalRequest,
    RetrievalResponse,
)
from backend.app.retrieval.service import (
    DEFAULT_TOP_K,
    SemanticRetrievalService,
)


def _create_mock_768_vector(seed: float = 0.1) -> List[float]:
    """Generate a valid 768-dimensional float vector for testing."""
    return [round(math.sin(seed + i * 0.01), 6) for i in range(768)]


# ---------------------------------------------------------------------------
# Unit Tests: Query Embedding and Citations
# ---------------------------------------------------------------------------

def test_query_embedding_with_search_query_prefix():
    """Verify that embed_query applies 'search_query: ' prefix and validates 768 dimensions."""
    mock_vec = _create_mock_768_vector(0.5)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "model": "nomic-embed-text",
        "embeddings": [mock_vec],
    }

    mock_http_client = MagicMock(spec=httpx.Client)
    mock_http_client.post.return_value = mock_response

    client = OllamaEmbeddingClient(
        base_url="http://localhost:11434",
        model="nomic-embed-text",
        http_client=mock_http_client,
    )

    vec = client.embed_query("How do founders understand customers?")

    assert len(vec) == 768
    assert vec == mock_vec

    # Verify search_query: prefix was prepended
    mock_http_client.post.assert_called_once()
    call_args = mock_http_client.post.call_args
    sent_payload = call_args[1]["json"]
    assert sent_payload["model"] == "nomic-embed-text"
    assert sent_payload["input"] == ["search_query: How do founders understand customers?"]


def test_empty_and_whitespace_query_rejection():
    """Verify that empty or whitespace-only search questions raise ValueError."""
    client = OllamaEmbeddingClient()

    with pytest.raises(ValueError, match="cannot be empty"):
        client.embed_query("")

    with pytest.raises(ValueError, match="cannot be empty"):
        client.embed_query("    \n\t  ")


def test_citation_url_standard_watch_url():
    """Verify timestamp query parameter is added cleanly to a standard watch URL."""
    url = build_timestamped_youtube_url(
        youtube_url="https://www.youtube.com/watch?v=4ef0juAMqoE",
        start_seconds=135.0,
    )
    assert url == "https://www.youtube.com/watch?v=4ef0juAMqoE&t=135s"


def test_citation_url_preserves_existing_query_params():
    """Verify existing query parameters are preserved when appending timestamp."""
    url = build_timestamped_youtube_url(
        youtube_url="https://www.youtube.com/watch?v=4ef0juAMqoE&feature=shared",
        start_seconds=65.0,
    )
    assert "v=4ef0juAMqoE" in url
    assert "feature=shared" in url
    assert "t=65s" in url


def test_citation_url_updates_existing_timestamp():
    """Verify that an existing timestamp parameter is updated rather than duplicated."""
    url = build_timestamped_youtube_url(
        youtube_url="https://www.youtube.com/watch?v=4ef0juAMqoE&t=10s",
        start_seconds=120.0,
    )
    assert url == "https://www.youtube.com/watch?v=4ef0juAMqoE&t=120s"
    assert url.count("t=") == 1


def test_citation_url_short_youtu_be():
    """Verify timestamp formatting for youtu.be short URLs."""
    url = build_timestamped_youtube_url(
        youtube_url="https://youtu.be/4ef0juAMqoE",
        start_seconds=45.0,
    )
    assert url == "https://youtu.be/4ef0juAMqoE?t=45s"


def test_citation_url_fallback_to_video_id():
    """Verify construction of watch URL when youtube_url is missing but video_id exists."""
    url = build_timestamped_youtube_url(
        youtube_url=None,
        video_id="4ef0juAMqoE",
        start_seconds=30.0,
    )
    assert url == "https://www.youtube.com/watch?v=4ef0juAMqoE&t=30s"


def test_citation_url_missing_timestamp_returns_base_url():
    """Verify that a missing timestamp returns the base episode URL without adding t."""
    url = build_timestamped_youtube_url(
        youtube_url="https://www.youtube.com/watch?v=4ef0juAMqoE",
        start_seconds=None,
    )
    assert url == "https://www.youtube.com/watch?v=4ef0juAMqoE"


def test_citation_url_missing_url_and_video_id_returns_none():
    """Verify that None is returned when no URL or video ID is available (never fabricates)."""
    assert build_timestamped_youtube_url(youtube_url=None, video_id=None, start_seconds=60.0) is None
    assert build_timestamped_youtube_url(youtube_url="", video_id="", start_seconds=60.0) is None


def test_format_seconds_to_timestamp():
    """Verify formatting seconds into HH:MM:SS or MM:SS strings."""
    assert format_seconds_to_timestamp(0.0) == "00:00"
    assert format_seconds_to_timestamp(65.0) == "01:05"
    assert format_seconds_to_timestamp(3720.0) == "01:02:00"
    assert format_seconds_to_timestamp(None) is None
    assert format_seconds_to_timestamp(-5.0) is None


# ---------------------------------------------------------------------------
# Integration Tests: Semantic Vector Retrieval Service
# ---------------------------------------------------------------------------

@pytest.fixture
def indexed_episodes_data(db_session: Session) -> List[TranscriptChunk]:
    """Fixture creating sample episodes, chunks, and embeddings."""
    ep1 = create_episode(
        db_session,
        {
            "slug": "brian-chesky",
            "guest_name": "Brian Chesky",
            "title": "Brian Chesky on Building Airbnb",
            "publish_date": date(2023, 11, 12),
            "youtube_url": "https://www.youtube.com/watch?v=4ef0juAMqoE",
            "video_id": "4ef0juAMqoE",
            "transcript_text": "Full transcript for Brian Chesky.",
            "content_checksum": "chk_chesky_1",
        },
    )
    ep2 = create_episode(
        db_session,
        {
            "slug": "elena-verna",
            "guest_name": "Elena Verna",
            "title": "Elena Verna on B2B Growth",
            "publish_date": date(2023, 4, 16),
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "video_id": "dQw4w9WgXcQ",
            "transcript_text": "Full transcript for Elena Verna.",
            "content_checksum": "chk_verna_1",
        },
    )

    chunks = create_chunks(
        db_session,
        [
            {
                "episode_id": ep1.id,
                "chunk_index": 0,
                "content": "Leaders must be in the details. Clarity allows everyone to row in the same direction.",
                "char_start": 0,
                "char_end": 85,
                "start_seconds": 0.0,
                "end_seconds": 65.0,
                "source_checksum": "chk_c1",
            },
            {
                "episode_id": ep1.id,
                "chunk_index": 1,
                "content": "When the pandemic hit, our business dropped by eighty percent in eight weeks.",
                "char_start": 86,
                "char_end": 170,
                "start_seconds": 135.0,
                "end_seconds": 195.0,
                "source_checksum": "chk_c2",
            },
            {
                "episode_id": ep2.id,
                "chunk_index": 0,
                "content": "Product-led growth works best when product usage drives customer acquisition directly.",
                "char_start": 0,
                "char_end": 88,
                "start_seconds": 10.0,
                "end_seconds": 70.0,
                "source_checksum": "chk_v1",
            },
        ],
    )

    # Attach vectors:
    # chunk 0: highly aligned with seed 0.1
    # chunk 1: aligned with seed 0.5
    # chunk 2: aligned with seed 0.9
    create_or_update_embedding(
        db_session,
        chunk_id=chunks[0].id,
        embedding=_create_mock_768_vector(0.1),
        model_name="nomic-embed-text",
        input_checksum="chk_emb_0",
    )
    create_or_update_embedding(
        db_session,
        chunk_id=chunks[1].id,
        embedding=_create_mock_768_vector(0.5),
        model_name="nomic-embed-text",
        input_checksum="chk_emb_1",
    )
    create_or_update_embedding(
        db_session,
        chunk_id=chunks[2].id,
        embedding=_create_mock_768_vector(0.9),
        model_name="nomic-embed-text",
        input_checksum="chk_emb_2",
    )

    return chunks


def test_semantic_search_cosine_ordering_and_deterministic_tie_breaking(
    db_session: Session, indexed_episodes_data: List[TranscriptChunk]
):
    """Verify that semantic retrieval returns nearest vectors ordered by distance ascending."""
    # Query vector matches chunk 0 (seed 0.1) exactly
    query_vector = _create_mock_768_vector(0.1)

    mock_client = MagicMock(spec=OllamaEmbeddingClient)
    mock_client.model = "nomic-embed-text"
    mock_client.dimensions = 768
    mock_client.embed_query.return_value = query_vector

    service = SemanticRetrievalService(db=db_session, client=mock_client)
    response = service.retrieve(query="Being in the details as a leader", top_k=3)

    assert response.status == "success"
    assert len(response.items) == 3

    # Top match must be chunk 0 with near 0.0 distance and 1.0 similarity
    top = response.items[0]
    assert top.chunk_id == indexed_episodes_data[0].id
    assert top.episode_title == "Brian Chesky on Building Airbnb"
    assert top.guest_name == "Brian Chesky"
    assert "Leaders must be in the details" in top.content
    assert top.cosine_distance == pytest.approx(0.0, abs=1e-4)
    assert top.similarity_score == pytest.approx(1.0, abs=1e-4)

    # Monotonically increasing distance (nearest first)
    assert response.items[0].cosine_distance <= response.items[1].cosine_distance
    assert response.items[1].cosine_distance <= response.items[2].cosine_distance


def test_model_filtering_excludes_other_models(db_session: Session, indexed_episodes_data: List[TranscriptChunk]):
    """Verify that search filters strictly by model_name and ignores embeddings from other models."""
    query_vector = _create_mock_768_vector(0.1)

    mock_client = MagicMock(spec=OllamaEmbeddingClient)
    mock_client.model = "other-model-v2"
    mock_client.dimensions = 768
    mock_client.embed_query.return_value = query_vector

    service = SemanticRetrievalService(db=db_session, client=mock_client, model="other-model-v2")
    response = service.retrieve(query="Any query", top_k=5)

    # Since no embeddings exist for "other-model-v2", report no_indexed_content
    assert response.status == "no_indexed_content"
    assert len(response.items) == 0


def test_source_metadata_and_verbatim_excerpts(
    db_session: Session, indexed_episodes_data: List[TranscriptChunk]
):
    """Verify all citation metadata fields, timestamp labels, and verbatim excerpts are present."""
    query_vector = _create_mock_768_vector(0.5)

    mock_client = MagicMock(spec=OllamaEmbeddingClient)
    mock_client.model = "nomic-embed-text"
    mock_client.dimensions = 768
    mock_client.embed_query.return_value = query_vector

    service = SemanticRetrievalService(db=db_session, client=mock_client)
    response = service.retrieve(query="Pandemic drop in business", top_k=1)

    assert response.status == "success"
    item = response.items[0]

    assert item.episode_slug == "brian-chesky"
    assert item.chunk_index == 1
    assert item.start_seconds == 135.0
    assert item.timestamp_label == "02:15"
    assert item.timestamped_url == "https://www.youtube.com/watch?v=4ef0juAMqoE&t=135s"
    assert item.content == "When the pandemic hit, our business dropped by eighty percent in eight weeks."


def test_no_indexed_content_status(db_session: Session):
    """Verify that an empty vector database returns status 'no_indexed_content' without errors."""
    mock_client = MagicMock(spec=OllamaEmbeddingClient)
    mock_client.model = "nomic-embed-text"
    mock_client.dimensions = 768

    service = SemanticRetrievalService(db=db_session, client=mock_client)
    response = service.retrieve(query="Any query", top_k=5)

    assert response.status == "no_indexed_content"
    assert len(response.items) == 0
    assert response.coverage.indexed_chunks == 0
    assert "No vector embeddings exist" in response.disclaimer


def test_partial_index_coverage_reporting_and_disclaimer(
    db_session: Session, indexed_episodes_data: List[TranscriptChunk]
):
    """Verify honest partial index reporting when only a subset of the corpus is indexed."""
    # Add an unindexed episode to simulate partial corpus indexing
    create_episode(
        db_session,
        {
            "slug": "unindexed-episode",
            "guest_name": "Unindexed Guest",
            "title": "Unindexed Episode",
            "publish_date": date(2024, 2, 1),
            "transcript_text": "This episode has no chunks and no embeddings.",
            "content_checksum": "chk_unindexed",
        },
    )

    query_vector = _create_mock_768_vector(0.1)

    mock_client = MagicMock(spec=OllamaEmbeddingClient)
    mock_client.model = "nomic-embed-text"
    mock_client.dimensions = 768
    mock_client.embed_query.return_value = query_vector

    service = SemanticRetrievalService(db=db_session, client=mock_client)
    response = service.retrieve(query="Leadership tactics", top_k=2)

    cov = response.coverage
    assert cov.total_episodes == 3
    assert cov.indexed_episodes == 2
    assert cov.is_partial is True
    assert "Partial index" in cov.description
    assert response.disclaimer is not None
    assert "2 episodes out of 3 total podcast episodes" in response.disclaimer


def test_top_k_bounding(db_session: Session, indexed_episodes_data: List[TranscriptChunk]):
    """Verify top_k bounds between 1 and 10."""
    query_vector = _create_mock_768_vector(0.1)

    mock_client = MagicMock(spec=OllamaEmbeddingClient)
    mock_client.model = "nomic-embed-text"
    mock_client.dimensions = 768
    mock_client.embed_query.return_value = query_vector

    service = SemanticRetrievalService(db=db_session, client=mock_client)

    # Request top_k = 1 -> should return 1
    res1 = service.retrieve(query="details", top_k=1)
    assert len(res1.items) == 1

    # Request top_k = 0 -> clamped to 1
    res0 = service.retrieve(query="details", top_k=0)
    assert len(res0.items) == 1


def test_read_only_safety_makes_zero_db_modifications(
    db_session: Session, indexed_episodes_data: List[TranscriptChunk]
):
    """Verify that running retrieval makes zero database modifications."""
    initial_episodes = count_episodes(db_session)
    initial_chunks = count_chunks(db_session)
    initial_embeddings = count_embeddings(db_session)

    mock_client = MagicMock(spec=OllamaEmbeddingClient)
    mock_client.model = "nomic-embed-text"
    mock_client.dimensions = 768
    mock_client.embed_query.return_value = _create_mock_768_vector(0.1)

    service = SemanticRetrievalService(db=db_session, client=mock_client)
    service.retrieve(query="Testing read only safety", top_k=5)

    assert count_episodes(db_session) == initial_episodes
    assert count_chunks(db_session) == initial_chunks
    assert count_embeddings(db_session) == initial_embeddings


def test_ollama_failure_propagates_cleanly(db_session: Session, indexed_episodes_data: List[TranscriptChunk]):
    """Verify that an Ollama timeout or connection failure raises EmbeddingError."""
    mock_client = MagicMock(spec=OllamaEmbeddingClient)
    mock_client.model = "nomic-embed-text"
    mock_client.dimensions = 768
    mock_client.embed_query.side_effect = OllamaTimeoutError("Timed out contacting Ollama")

    service = SemanticRetrievalService(db=db_session, client=mock_client)

    with pytest.raises(EmbeddingError, match="Timed out"):
        service.retrieve(query="What is PLG?", top_k=3)


# ---------------------------------------------------------------------------
# CLI Integration Tests
# ---------------------------------------------------------------------------

def test_retrieval_cli_success(db_session: Session, indexed_episodes_data: List[TranscriptChunk]):
    """Verify that the retrieval CLI runs and outputs formatted citations with exit code 0."""
    import sys

    @contextmanager
    def mock_session_ctx():
        yield db_session

    mock_client = MagicMock(spec=OllamaEmbeddingClient)
    mock_client.model = "nomic-embed-text"
    mock_client.dimensions = 768
    mock_client.embed_query.return_value = _create_mock_768_vector(0.1)

    with patch("backend.app.retrieval.cli.get_db_session", side_effect=mock_session_ctx):
        with patch("backend.app.retrieval.service.OllamaEmbeddingClient", return_value=mock_client):
            with patch.object(
                sys,
                "argv",
                ["cli.py", "--query", "How do leaders get into the details?", "--top-k", "2"],
            ):
                exit_code = cli.main()

    assert exit_code == 0


def test_retrieval_cli_empty_query_error():
    """Verify that CLI rejects empty/whitespace query with exit code 1."""
    import sys

    with patch.object(sys, "argv", ["cli.py", "--query", "    "]):
        exit_code = cli.main()

    assert exit_code == 1


def test_retrieval_cli_unconfigured_database():
    """Verify that CLI returns exit code 2 when database is unconfigured."""
    import sys

    @contextmanager
    def mock_unconfigured():
        raise DatabaseUnconfiguredException("Database not configured.")
        yield  # pragma: no cover

    with patch("backend.app.retrieval.cli.get_db_session", side_effect=mock_unconfigured):
        with patch.object(sys, "argv", ["cli.py", "--query", "Valid query"]):
            exit_code = cli.main()

    assert exit_code == 2
