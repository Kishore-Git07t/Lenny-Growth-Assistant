"""Automated unit and integration tests for Ollama vector embedding pipeline (Phase 3.2B-2)."""

from contextlib import contextmanager
from datetime import date
import math
from typing import Any, List
import uuid
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.database import (
    DatabaseUnavailableException,
    DatabaseUnconfiguredException,
)
from backend.app.embeddings.client import (
    DEFAULT_DOC_PREFIX,
    DEFAULT_QUERY_PREFIX,
    EXPECTED_EMBEDDING_DIMENSIONS,
    EmbeddingDimensionError,
    EmbeddingError,
    OllamaConnectionError,
    OllamaEmbeddingClient,
    OllamaResponseError,
    OllamaTimeoutError,
)
from backend.app.embeddings.service import (
    EmbeddingReport,
    TranscriptEmbeddingService,
    compute_embedding_input_checksum,
)
import backend.app.embeddings.cli as cli
from backend.app.models.chunk import TranscriptChunk
from backend.app.models.embedding import TranscriptEmbedding
from backend.app.models.episode import PodcastEpisode
from backend.app.repositories.chunk_repository import create_chunks
from backend.app.repositories.embedding_repository import (
    count_embeddings,
    create_or_update_embedding,
    delete_embeddings_by_chunk_id,
    get_embedding_by_chunk_id,
    get_embedding_metadata_by_chunk_id,
)
from backend.app.repositories.episode_repository import create_episode


def _create_mock_768_vector(seed: float = 0.1) -> List[float]:
    """Generate a valid 768-dimensional float vector for testing."""
    return [round(math.sin(seed + i * 0.01), 6) for i in range(768)]


# ---------------------------------------------------------------------------
# Unit Tests: OllamaEmbeddingClient
# ---------------------------------------------------------------------------

def test_successful_embedding_generation_and_prefix():
    """Verify that embed_texts formats request, prepends document prefix, and returns validated 768-D vector."""
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

    results = client.embed_texts(["Product-led growth is a strategy."])

    assert len(results) == 1
    assert len(results[0]) == 768
    assert results[0] == mock_vec

    # Verify document prefix was prepended
    mock_http_client.post.assert_called_once()
    call_args = mock_http_client.post.call_args
    sent_payload = call_args[1]["json"]
    assert sent_payload["model"] == "nomic-embed-text"
    assert sent_payload["input"] == ["search_document: Product-led growth is a strategy."]


def test_prefix_idempotence():
    """Verify that inputs already prefixed with search_document: are not double-prefixed."""
    mock_vec = _create_mock_768_vector(0.2)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "model": "nomic-embed-text",
        "embeddings": [mock_vec],
    }

    mock_http_client = MagicMock(spec=httpx.Client)
    mock_http_client.post.return_value = mock_response

    client = OllamaEmbeddingClient(http_client=mock_http_client)
    client.embed_texts(["search_document: Already prefixed content"])

    sent_payload = mock_http_client.post.call_args[1]["json"]
    assert sent_payload["input"] == ["search_document: Already prefixed content"]


def test_rejection_of_incorrect_vector_dimensions():
    """Verify that response vectors with != 768 dimensions raise EmbeddingDimensionError."""
    # Under-dimensioned (512 dimensions)
    short_vec = [0.1] * 512

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "model": "nomic-embed-text",
        "embeddings": [short_vec],
    }

    mock_http_client = MagicMock(spec=httpx.Client)
    mock_http_client.post.return_value = mock_response

    client = OllamaEmbeddingClient(http_client=mock_http_client)

    with pytest.raises(EmbeddingDimensionError, match="expected exactly 768"):
        client.embed_texts(["Some text"])


def test_rejection_of_non_finite_vector_values():
    """Verify that vector values containing NaN or Infinity raise EmbeddingDimensionError."""
    nan_vec = _create_mock_768_vector(0.1)
    nan_vec[42] = float("nan")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "model": "nomic-embed-text",
        "embeddings": [nan_vec],
    }

    mock_http_client = MagicMock(spec=httpx.Client)
    mock_http_client.post.return_value = mock_response

    client = OllamaEmbeddingClient(http_client=mock_http_client)

    with pytest.raises(EmbeddingDimensionError, match="non-finite value"):
        client.embed_texts(["Text with NaN vector"])


def test_rejection_of_missing_or_malformed_response_fields():
    """Verify that Ollama responses missing the 'embeddings' list raise OllamaResponseError."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"error": "model not loaded"}

    mock_http_client = MagicMock(spec=httpx.Client)
    mock_http_client.post.return_value = mock_response

    client = OllamaEmbeddingClient(http_client=mock_http_client)

    with pytest.raises(OllamaResponseError, match="missing 'embeddings'"):
        client.embed_texts(["Some text"])


def test_ollama_404_model_not_found():
    """Verify that HTTP 404 from Ollama raises OllamaResponseError with instructions to pull model."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 404
    mock_response.text = "model 'nomic-embed-text' not found"

    mock_http_client = MagicMock(spec=httpx.Client)
    mock_http_client.post.return_value = mock_response

    client = OllamaEmbeddingClient(http_client=mock_http_client)

    with pytest.raises(OllamaResponseError, match="ollama pull"):
        client.embed_texts(["Some text"])


def test_ollama_timeout_handling():
    """Verify that network timeout raises OllamaTimeoutError."""
    mock_http_client = MagicMock(spec=httpx.Client)
    mock_http_client.post.side_effect = httpx.ReadTimeout("Connection timed out")

    client = OllamaEmbeddingClient(http_client=mock_http_client, max_retries=1)

    with pytest.raises(OllamaTimeoutError, match="timed out"):
        client.embed_texts(["Some text"])


def test_transient_retry_success():
    """Verify that transient server errors (HTTP 500) retry and succeed upon subsequent attempt."""
    mock_vec = _create_mock_768_vector(0.7)

    fail_response = MagicMock(spec=httpx.Response)
    fail_response.status_code = 500
    fail_response.text = "Internal error"

    success_response = MagicMock(spec=httpx.Response)
    success_response.status_code = 200
    success_response.json.return_value = {
        "model": "nomic-embed-text",
        "embeddings": [mock_vec],
    }

    mock_http_client = MagicMock(spec=httpx.Client)
    # Fail once, then succeed
    mock_http_client.post.side_effect = [fail_response, success_response]

    client = OllamaEmbeddingClient(
        http_client=mock_http_client,
        max_retries=2,
        backoff_factor=0.01,
    )

    results = client.embed_texts(["Text after retry"])
    assert len(results) == 1
    assert len(results[0]) == 768
    assert mock_http_client.post.call_count == 2


# ---------------------------------------------------------------------------
# Integration Tests: Database Persistence & Repository
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_chunk(db_session: Session) -> TranscriptChunk:
    """Fixture providing a saved PodcastEpisode and TranscriptChunk."""
    ep = create_episode(
        db_session,
        {
            "slug": "embedding-test-episode",
            "guest_name": "Test Guest",
            "title": "Embedding Test Episode",
            "publish_date": date(2024, 1, 1),
            "transcript_text": "Sample transcript text for embedding tests.",
            "content_checksum": "checksum_test_12345",
        },
    )
    chunks = create_chunks(
        db_session,
        [
            {
                "episode_id": ep.id,
                "chunk_index": 0,
                "content": "Sample transcript text passage for vector embedding testing.",
                "source_checksum": "checksum_test_12345",
            }
        ],
    )
    return chunks[0]


def test_database_insert_and_readback(db_session: Session, sample_chunk: TranscriptChunk):
    """Verify that 768-D vectors persist and read back from the database accurately."""
    mock_vec = _create_mock_768_vector(0.3)
    input_chk = compute_embedding_input_checksum(sample_chunk.content)

    record = create_or_update_embedding(
        db_session,
        chunk_id=sample_chunk.id,
        embedding=mock_vec,
        model_name="nomic-embed-text",
        input_checksum=input_chk,
        commit=True,
    )

    assert record.id is not None
    assert record.chunk_id == sample_chunk.id
    assert record.model_name == "nomic-embed-text"
    assert record.input_checksum == input_chk
    assert len(record.embedding) == 768
    assert record.embedding[0] == pytest.approx(mock_vec[0], abs=1e-5)

    # Readback via repository
    fetched = get_embedding_by_chunk_id(db_session, sample_chunk.id)
    assert fetched is not None
    assert fetched.chunk_id == sample_chunk.id
    assert len(fetched.embedding) == 768


def test_unique_constraint_one_embedding_per_chunk(db_session: Session, sample_chunk: TranscriptChunk):
    """Verify that chunk_id unique constraint prevents duplicate embedding rows."""
    mock_vec1 = _create_mock_768_vector(0.1)
    mock_vec2 = _create_mock_768_vector(0.2)

    create_or_update_embedding(
        db_session,
        chunk_id=sample_chunk.id,
        embedding=mock_vec1,
        model_name="nomic-embed-text",
        input_checksum="chk_1",
        commit=True,
    )

    # Attempt manual insert with same chunk_id -> must violate unique constraint
    dup = TranscriptEmbedding(
        id=uuid.uuid4(),
        chunk_id=sample_chunk.id,
        embedding=mock_vec2,
        model_name="nomic-embed-text",
        input_checksum="chk_2",
    )
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_cascade_deletion_on_chunk_removal(db_session: Session, sample_chunk: TranscriptChunk):
    """Verify that deleting a transcript chunk automatically cascades to delete its embedding."""
    mock_vec = _create_mock_768_vector(0.4)
    create_or_update_embedding(
        db_session,
        chunk_id=sample_chunk.id,
        embedding=mock_vec,
        model_name="nomic-embed-text",
        input_checksum="chk_cascade",
        commit=True,
    )

    assert count_embeddings(db_session) == 1

    # Delete parent chunk
    db_session.delete(sample_chunk)
    db_session.commit()

    assert count_embeddings(db_session) == 0


# ---------------------------------------------------------------------------
# Integration Tests: TranscriptEmbeddingService Pipeline
# ---------------------------------------------------------------------------

def test_idempotent_repeated_embedding_processing(db_session: Session, sample_chunk: TranscriptChunk):
    """Verify that repeated runs skip chunks whose checksum and model match without calling Ollama."""
    mock_vec = _create_mock_768_vector(0.5)

    mock_client = MagicMock(spec=OllamaEmbeddingClient)
    mock_client.model = "nomic-embed-text"
    mock_client.dimensions = 768
    mock_client.embed_texts.return_value = [mock_vec]

    service = TranscriptEmbeddingService(db=db_session, client=mock_client, batch_size=4)

    # Run 1: First generation
    report1 = service.embed_chunks(dry_run=False)
    assert report1.total_chunks_inspected == 1
    assert report1.chunks_embedded == 1
    assert report1.chunks_skipped == 0
    assert mock_client.embed_texts.call_count == 1
    assert count_embeddings(db_session) == 1

    # Run 2: Re-run with unchanged chunk -> must skip Ollama call
    mock_client.embed_texts.reset_mock()
    report2 = service.embed_chunks(dry_run=False)
    assert report2.total_chunks_inspected == 1
    assert report2.chunks_embedded == 0
    assert report2.chunks_skipped == 1
    assert mock_client.embed_texts.call_count == 0
    assert count_embeddings(db_session) == 1


def test_content_change_triggers_re_embedding(db_session: Session, sample_chunk: TranscriptChunk):
    """Verify that modifying a chunk's content causes the pipeline to regenerate its embedding."""
    mock_vec1 = _create_mock_768_vector(0.1)
    mock_vec2 = _create_mock_768_vector(0.9)

    mock_client = MagicMock(spec=OllamaEmbeddingClient)
    mock_client.model = "nomic-embed-text"
    mock_client.dimensions = 768
    mock_client.embed_texts.return_value = [mock_vec1]

    service = TranscriptEmbeddingService(db=db_session, client=mock_client)

    # Run 1: Initial embed
    report1 = service.embed_chunks(dry_run=False)
    assert report1.chunks_embedded == 1

    # Modify chunk content
    sample_chunk.content = "Completely updated transcript content with new growth lessons."
    db_session.commit()

    # Run 2: Pipeline should detect checksum mismatch and update
    mock_client.embed_texts.return_value = [mock_vec2]
    report2 = service.embed_chunks(dry_run=False)
    assert report2.chunks_updated == 1
    assert report2.chunks_skipped == 0

    emb = get_embedding_by_chunk_id(db_session, sample_chunk.id)
    assert emb.embedding[0] == pytest.approx(mock_vec2[0], abs=1e-5)


def test_model_change_triggers_re_embedding(db_session: Session, sample_chunk: TranscriptChunk):
    """Verify that switching the target model triggers regeneration."""
    mock_vec1 = _create_mock_768_vector(0.1)
    mock_vec2 = _create_mock_768_vector(0.2)

    client1 = MagicMock(spec=OllamaEmbeddingClient)
    client1.model = "old-model-v1"
    client1.dimensions = 768
    client1.embed_texts.return_value = [mock_vec1]

    service1 = TranscriptEmbeddingService(db=db_session, client=client1)
    report1 = service1.embed_chunks(dry_run=False)
    assert report1.chunks_embedded == 1

    # Switch to new model
    client2 = MagicMock(spec=OllamaEmbeddingClient)
    client2.model = "nomic-embed-text"
    client2.dimensions = 768
    client2.embed_texts.return_value = [mock_vec2]

    service2 = TranscriptEmbeddingService(db=db_session, client=client2)
    report2 = service2.embed_chunks(dry_run=False)
    assert report2.chunks_updated == 1

    emb = get_embedding_by_chunk_id(db_session, sample_chunk.id)
    assert emb.model_name == "nomic-embed-text"


def test_dry_run_performs_zero_ollama_calls_and_zero_writes(db_session: Session, sample_chunk: TranscriptChunk):
    """Verify that dry-run mode estimates pending work without calling Ollama or modifying the DB."""
    mock_client = MagicMock(spec=OllamaEmbeddingClient)
    mock_client.model = "nomic-embed-text"
    mock_client.dimensions = 768

    service = TranscriptEmbeddingService(db=db_session, client=mock_client)
    report = service.embed_chunks(dry_run=True)

    assert report.dry_run is True
    assert report.total_chunks_inspected == 1
    assert report.chunks_embedded == 1
    assert report.chunks_skipped == 0
    assert mock_client.embed_texts.call_count == 0
    assert count_embeddings(db_session) == 0


def test_failed_batch_preserves_previously_completed_embeddings(db_session: Session):
    """Verify that if batch 2 fails, batch 1 embeddings remain committed and the session recovers."""
    ep = create_episode(
        db_session,
        {
            "slug": "two-batch-episode",
            "guest_name": "Multi Guest",
            "title": "Two Batch Episode",
            "transcript_text": "Text for two batches.",
            "content_checksum": "chk_two_batch",
        },
    )
    chunks = create_chunks(
        db_session,
        [
            {"episode_id": ep.id, "chunk_index": 0, "content": "Batch 1 Chunk 1", "source_checksum": "c1"},
            {"episode_id": ep.id, "chunk_index": 1, "content": "Batch 1 Chunk 2", "source_checksum": "c2"},
            {"episode_id": ep.id, "chunk_index": 2, "content": "Batch 2 Chunk 1", "source_checksum": "c3"},
            {"episode_id": ep.id, "chunk_index": 3, "content": "Batch 2 Chunk 2", "source_checksum": "c4"},
        ],
    )

    vec1 = _create_mock_768_vector(0.1)
    vec2 = _create_mock_768_vector(0.2)

    mock_client = MagicMock(spec=OllamaEmbeddingClient)
    mock_client.model = "nomic-embed-text"
    mock_client.dimensions = 768
    # First batch of 2 succeeds, second batch of 2 raises connection error
    mock_client.embed_texts.side_effect = [
        [vec1, vec2],
        OllamaConnectionError("Simulated Ollama crash on batch 2"),
    ]

    service = TranscriptEmbeddingService(db=db_session, client=mock_client, batch_size=2)
    report = service.embed_chunks(dry_run=False, max_errors=10)

    assert report.chunks_embedded == 2
    assert report.chunks_failed == 2
    # Batch 1 records must survive in the database
    assert count_embeddings(db_session) == 2
    assert get_embedding_by_chunk_id(db_session, chunks[0].id) is not None
    assert get_embedding_by_chunk_id(db_session, chunks[1].id) is not None


# ---------------------------------------------------------------------------
# CLI Integration Tests
# ---------------------------------------------------------------------------

def test_embedding_cli_dry_run_workflow(db_session: Session, sample_chunk: TranscriptChunk):
    """Verify that CLI in dry-run mode previews work without writing to the database."""
    import sys

    @contextmanager
    def mock_session_ctx():
        yield db_session

    with patch("backend.app.embeddings.cli.get_db_session", side_effect=mock_session_ctx):
        with patch.object(sys, "argv", ["cli.py", "--dry-run", "--limit", "1"]):
            exit_code = cli.main()

    assert exit_code == 0
    assert count_embeddings(db_session) == 0


def test_embedding_cli_zero_chunks_found(db_session: Session):
    """Verify that CLI returns exit code 1 when no chunks exist in the database."""
    import sys

    @contextmanager
    def mock_session_ctx():
        yield db_session

    with patch("backend.app.embeddings.cli.get_db_session", side_effect=mock_session_ctx):
        with patch.object(sys, "argv", ["cli.py", "--dry-run"]):
            exit_code = cli.main()

    assert exit_code == 1


def test_embedding_cli_unconfigured_database():
    """Verify that CLI returns exit code 2 when database is unconfigured."""
    import sys

    @contextmanager
    def mock_unconfigured():
        raise DatabaseUnconfiguredException("Database not configured.")
        yield  # pragma: no cover

    with patch("backend.app.embeddings.cli.get_db_session", side_effect=mock_unconfigured):
        with patch.object(sys, "argv", ["cli.py", "--dry-run"]):
            exit_code = cli.main()

    assert exit_code == 2
