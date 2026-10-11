"""Automated unit and integration tests for transcript chunking foundation."""

from contextlib import contextmanager
from datetime import date
from typing import Generator
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.chunking.chunker import (
    ChunkingConfig,
    chunk_transcript_text,
    extract_timestamps_from_text,
    parse_timestamp_to_seconds,
    segment_into_units,
)
from backend.app.chunking.service import TranscriptChunkingService
import backend.app.chunking.cli as cli
from backend.app.database import (
    DatabaseUnavailableException,
    DatabaseUnconfiguredException,
)
from backend.app.models.chunk import TranscriptChunk
from backend.app.models.episode import PodcastEpisode
from backend.app.repositories.chunk_repository import (
    count_chunks,
    count_chunks_for_episode,
    create_chunks,
    get_chunks_by_episode_id,
)
from backend.app.repositories.episode_repository import (
    count_episodes,
    create_episode,
    get_episode_by_id,
)


SAMPLE_MULTI_TURN_TRANSCRIPT = """# Brian Chesky on Building Airbnb

## Transcript

Brian Chesky (00:00:00):
Way too many founders apologize for how they want to run the company. They find some midpoint between how they want to run a company and how the people they lead want to run the company. That is a good way to make everyone miserable because what everyone really wants is clarity. When you have clarity, everyone rows in the same direction really quickly. I got involved in every single detail. Leaders are in the details. People confuse micromanagement with being in the details. Being in the details is what every responsible board does.

Lenny (00:01:05):
Welcome to Lenny's Podcast. Today my guest is Brian Chesky, co-founder and CEO of Airbnb. Brian started Airbnb in his apartment with Joe and Nate, and grew it into an 80 billion dollar global business across 220 countries. In this episode, Brian shares his playbook on product management, why he eliminated traditional product management roles, and how Airbnb operates with a single unified company roadmap.

Brian Chesky (00:02:15):
When the pandemic hit, our business dropped by 80 percent in eight weeks. We had to rethink everything from the ground up. We simplified our offerings, cut distractions, and went back to the core design-led ethos that made Airbnb special in the first place.
"""

SAMPLE_SHORT_TRANSCRIPT = """Lenny (00:00:00):
Welcome to a short test episode.

Guest (00:00:10):
Thank you Lenny, excited to be here and discuss product growth.
"""

SAMPLE_NO_TIMESTAMP_TRANSCRIPT = """# Raw Transcript Without Timestamps

Lenny: Welcome to the podcast. Today we are discussing product growth, retention, and monetization strategies for early stage startups.

Guest: Thank you Lenny. The most critical metric early on is retention because without retention, customer acquisition simply fills a leaky bucket.
"""

# Generates an 800+ word continuous monologue to test breaking large speaker turns
def _generate_long_monologue() -> str:
    sentences = [
        "In the early days of building our product, we realized that user onboarding was the highest leverage funnel.",
        "Every single reduction in friction yielded a measurable improvement in second week retention.",
        "We interviewed hundreds of churned users and learned that the core value proposition was often misunderstood.",
        "Rather than adding more features, we removed sixty percent of the settings and focused on the primary job to be done.",
        "Our engineering team established strict latency budgets because every hundred milliseconds of delay reduced conversions.",
        "Design systems allowed our product teams to prototype and iterate three times faster than before.",
        "We instituted weekly design reviews where the entire leadership team reviewed every single customer facing surface.",
        "Marketing and product were unified under one single growth function to align incentives across the acquisition loop.",
        "By aligning paid channels with organic viral loops, our customer acquisition cost dropped by over fifty percent.",
        "Ultimately, sustainable growth came down to delivering an indispensable product that users organically recommended.",
    ]
    # Repeat sentences to exceed 800 words
    full_monologue = "Brian Chesky (00:05:00):\n" + " ".join(sentences * 6)
    return full_monologue


# ---------------------------------------------------------------------------
# Unit Tests: Chunker Logic & Timestamp Parsing
# ---------------------------------------------------------------------------

def test_parse_timestamp_to_seconds():
    """Verify that timestamp strings in various formats parse accurately into float seconds."""
    assert parse_timestamp_to_seconds("00:00:00") == 0.0
    assert parse_timestamp_to_seconds("00:01:05") == 65.0
    assert parse_timestamp_to_seconds("01:13:28") == 4408.0
    assert parse_timestamp_to_seconds("05:04") == 304.0
    assert parse_timestamp_to_seconds("(00:02:15)") == 135.0
    assert parse_timestamp_to_seconds("[00:10:30]") == 630.0
    assert parse_timestamp_to_seconds("not-a-time") is None
    assert parse_timestamp_to_seconds("") is None


def test_extract_timestamps_from_text():
    """Verify regex extraction of multiple timestamps from dialogue text."""
    text = "Brian (00:00:00): Hello! Then later at (00:01:30) and [00:05:45] we concluded."
    ts = extract_timestamps_from_text(text)
    assert ts == [0.0, 90.0, 345.0]


def test_short_transcript_produces_single_chunk():
    """Verify that a short transcript under target_words produces exactly one complete chunk."""
    chunks = chunk_transcript_text(SAMPLE_SHORT_TRANSCRIPT, ChunkingConfig(target_words=300))
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_index == 0
    assert "Welcome to a short test episode" in chunk.content
    assert "excited to be here" in chunk.content
    assert chunk.word_count > 0
    assert chunk.start_seconds == 0.0
    assert chunk.end_seconds == 10.0


def test_normal_transcript_chunking_with_boundaries():
    """Verify normal transcript chunking targeting ~250-400 words without cutting words."""
    cfg = ChunkingConfig(target_words=100, max_words=200, overlap_words=30)
    chunks = chunk_transcript_text(SAMPLE_MULTI_TURN_TRANSCRIPT, cfg)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.word_count > 0
        assert chunk.word_count <= cfg.max_words
        assert chunk.char_start >= 0
        assert chunk.char_end > chunk.char_start
        # Verbatim substring verification
        assert SAMPLE_MULTI_TURN_TRANSCRIPT[chunk.char_start:chunk.char_end].strip() == chunk.content


def test_long_speaker_turn_is_broken_without_unbounded_chunks():
    """Verify that a massive monologue is broken cleanly across sentence boundaries without exceeding max_words."""
    monologue = _generate_long_monologue()
    cfg = ChunkingConfig(target_words=200, max_words=350, overlap_words=40)
    chunks = chunk_transcript_text(monologue, cfg)

    assert len(chunks) >= 3
    for chunk in chunks:
        assert chunk.word_count <= cfg.max_words
        # Ensure chunks end cleanly on punctuation
        assert chunk.content[-1] in (".", "?", "!", '"', "'")


def test_chunk_overlap_correctness():
    """Verify that consecutive chunks share overlapping context across boundaries."""
    cfg = ChunkingConfig(target_words=100, max_words=200, overlap_words=30)
    chunks = chunk_transcript_text(SAMPLE_MULTI_TURN_TRANSCRIPT, cfg)

    assert len(chunks) >= 2
    # Verify adjacent chunks share text
    for i in range(len(chunks) - 1):
        words_first = set(chunks[i].content.split()[-20:])
        words_second = set(chunks[i + 1].content.split()[:20])
        common = words_first.intersection(words_second)
        assert len(common) > 0, f"Expected overlap between chunk {i} and {i+1}"


def test_no_empty_chunks_and_full_content_coverage():
    """Verify that no chunks are empty, exact verbatim wording is retained, and all transcript units are represented."""
    cfg = ChunkingConfig(target_words=80)
    chunks = chunk_transcript_text(SAMPLE_MULTI_TURN_TRANSCRIPT, cfg)
    assert len(chunks) > 0

    for chunk in chunks:
        assert len(chunk.content.strip()) > 0
        assert chunk.word_count > 0
        # Exact verbatim substring without content modification
        assert SAMPLE_MULTI_TURN_TRANSCRIPT[chunk.char_start:chunk.char_end] == chunk.content

    # 1. Verify key dialogue from beginning, middle, and end are captured
    full_text = " ".join(c.content for c in chunks)
    assert "Way too many founders apologize" in full_text
    assert "Lenny's Podcast" in full_text
    assert "80 percent in eight weeks" in full_text

    # 2. Comprehensive semantic unit coverage: every segmented unit must be present in at least one chunk
    all_units = segment_into_units(SAMPLE_MULTI_TURN_TRANSCRIPT, target_words=cfg.target_words)
    for u in all_units:
        assert any(u.text in c.content for c in chunks), f"Missing source unit from chunks: {u.text[:40]}"

    # 3. Continuous boundary coverage: chunks must overlap or touch with zero missing span gap
    for i in range(len(chunks) - 1):
        assert chunks[i + 1].char_start <= chunks[i].char_end, (
            f"Coverage gap detected between chunk {i} (end {chunks[i].char_end}) "
            f"and chunk {i+1} (start {chunks[i+1].char_start})"
        )


def test_deterministic_chunking_output():
    """Verify that running chunking multiple times on identical input produces identical results."""
    cfg = ChunkingConfig(target_words=150, max_words=250, overlap_words=30)
    run1 = chunk_transcript_text(SAMPLE_MULTI_TURN_TRANSCRIPT, cfg)
    run2 = chunk_transcript_text(SAMPLE_MULTI_TURN_TRANSCRIPT, cfg)

    assert len(run1) == len(run2)
    for c1, c2 in zip(run1, run2):
        assert c1.chunk_index == c2.chunk_index
        assert c1.content == c2.content
        assert c1.char_start == c2.char_start
        assert c1.char_end == c2.char_end
        assert c1.start_seconds == c2.start_seconds
        assert c1.end_seconds == c2.end_seconds


def test_missing_timestamp_handling():
    """Verify that transcripts without timestamps produce chunks with NULL/None timestamps."""
    chunks = chunk_transcript_text(SAMPLE_NO_TIMESTAMP_TRANSCRIPT, ChunkingConfig(target_words=50))
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.start_seconds is None
        assert chunk.end_seconds is None


# ---------------------------------------------------------------------------
# Integration Tests: Database Persistence & Service Idempotency
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_episode(db_session: Session) -> PodcastEpisode:
    """Fixture providing a saved PodcastEpisode in the test database."""
    episode = create_episode(
        db_session,
        {
            "slug": "brian-chesky",
            "guest_name": "Brian Chesky",
            "title": "Brian Chesky's Playbook",
            "publish_date": date(2023, 11, 12),
            "youtube_url": "https://www.youtube.com/watch?v=4ef0juAMqoE",
            "video_id": "4ef0juAMqoE",
            "source_path": "episodes/brian-chesky/transcript.md",
            "description": "Brian Chesky interview",
            "transcript_text": SAMPLE_MULTI_TURN_TRANSCRIPT,
            "content_checksum": "checksum_chesky_initial_12345",
            "raw_metadata": {"duration_seconds": 4408},
        },
    )
    return episode


def test_chunk_to_episode_database_association(db_session: Session, sample_episode: PodcastEpisode):
    """Verify that chunks are persisted and properly associated with their parent episode."""
    service = TranscriptChunkingService(db=db_session, config=ChunkingConfig(target_words=100))
    detail = service.process_episode(sample_episode, dry_run=False)

    assert detail.status == "processed"
    assert detail.chunks_count > 0

    chunks = get_chunks_by_episode_id(db_session, sample_episode.id)
    assert len(chunks) == detail.chunks_count

    for idx, chunk in enumerate(chunks):
        assert chunk.episode_id == sample_episode.id
        assert chunk.chunk_index == idx
        assert chunk.source_checksum == sample_episode.content_checksum
        assert chunk.config_fingerprint == service.config.fingerprint()
        assert chunk.word_count > 0
        assert len(chunk.content) > 0


def test_duplicate_prevention_unique_constraint(db_session: Session, sample_episode: PodcastEpisode):
    """Verify that attempting to insert duplicate (episode_id, chunk_index) violates unique constraint."""
    chunks_data = [
        {
            "episode_id": sample_episode.id,
            "chunk_index": 0,
            "content": "First chunk content",
            "source_checksum": sample_episode.content_checksum,
        },
        {
            "episode_id": sample_episode.id,
            "chunk_index": 0,  # Duplicate chunk_index for same episode
            "content": "Conflicting duplicate chunk",
            "source_checksum": sample_episode.content_checksum,
        },
    ]

    with pytest.raises(IntegrityError):
        create_chunks(db_session, chunks_data)
    db_session.rollback()


def test_idempotent_repeated_chunking(db_session: Session, sample_episode: PodcastEpisode):
    """Verify that repeated chunking runs skip episodes whose checksums are already current."""
    service = TranscriptChunkingService(db=db_session, config=ChunkingConfig(target_words=100))

    # Run 1: Process new episode
    detail1 = service.process_episode(sample_episode, dry_run=False)
    assert detail1.status == "processed"
    initial_chunk_count = count_chunks(db_session)
    assert initial_chunk_count > 0

    # Run 2: Re-run with unchanged episode
    detail2 = service.process_episode(sample_episode, dry_run=False)
    assert detail2.status == "skipped"
    assert detail2.chunks_count == initial_chunk_count

    # Total database chunks must remain unchanged
    assert count_chunks(db_session) == initial_chunk_count


def test_changed_transcript_re_chunking(db_session: Session, sample_episode: PodcastEpisode):
    """Verify that when an episode transcript checksum changes, old chunks are rebuilt without duplicates."""
    service = TranscriptChunkingService(db=db_session, config=ChunkingConfig(target_words=100))

    # Run 1: Initial chunking
    detail1 = service.process_episode(sample_episode, dry_run=False)
    assert detail1.status == "processed"

    # Simulate transcript update with new checksum and additional dialogue
    sample_episode.content_checksum = "checksum_chesky_updated_99999"
    sample_episode.transcript_text += "\n\nLenny (00:03:00):\nOne final question about company culture."
    db_session.commit()

    # Run 2: Re-run chunking
    detail2 = service.process_episode(sample_episode, dry_run=False)
    assert detail2.status == "updated"

    # Verify all current chunks have the new checksum
    current_chunks = get_chunks_by_episode_id(db_session, sample_episode.id)
    assert len(current_chunks) == detail2.chunks_count
    for c in current_chunks:
        assert c.source_checksum == "checksum_chesky_updated_99999"


def test_database_rollback_on_chunking_error(db_session: Session, sample_episode: PodcastEpisode):
    """Verify that database errors during chunking trigger rollback, leave session clean, and preserve parent episode."""
    from unittest.mock import patch

    service = TranscriptChunkingService(db=db_session)
    ep_id = sample_episode.id

    with patch("backend.app.chunking.service.create_chunks", side_effect=RuntimeError("Simulated DB Write Error")):
        detail = service.process_episode(sample_episode, dry_run=False)

    assert detail.status == "failed"
    assert "Simulated DB Write Error" in detail.error
    # Zero chunks persisted
    assert count_chunks_for_episode(db_session, ep_id) == 0
    # Parent episode remains persisted in the database
    assert get_episode_by_id(db_session, ep_id) is not None


def test_session_recovery_after_chunking_error(db_session: Session, sample_episode: PodcastEpisode):
    """Verify that after a rollback on one episode, the session recovers and can process other episodes."""
    from unittest.mock import patch

    service = TranscriptChunkingService(db=db_session, config=ChunkingConfig(target_words=100))
    ep1_id = sample_episode.id

    # Second episode
    episode2 = create_episode(
        db_session,
        {
            "slug": "second-guest",
            "guest_name": "Second Guest",
            "title": "Second Episode",
            "transcript_text": SAMPLE_SHORT_TRANSCRIPT,
            "content_checksum": "checksum_second_12345",
        },
    )
    ep2_id = episode2.id

    # 1. First episode fails with DB error
    with patch("backend.app.chunking.service.create_chunks", side_effect=RuntimeError("Simulated DB Write Error")):
        detail1 = service.process_episode(sample_episode, dry_run=False)

    assert detail1.status == "failed"
    assert count_chunks_for_episode(db_session, ep1_id) == 0

    # 2. Second episode succeeds without error using the same session
    detail2 = service.process_episode(episode2, dry_run=False)
    assert detail2.status == "processed"
    assert detail2.chunks_count > 0
    assert count_chunks_for_episode(db_session, ep2_id) == detail2.chunks_count
    # Both episodes remain persisted
    assert get_episode_by_id(db_session, ep1_id) is not None
    assert get_episode_by_id(db_session, ep2_id) is not None


def test_preservation_of_valid_chunks_after_failed_replacement(db_session: Session, sample_episode: PodcastEpisode):
    """Verify that if an update fails during chunk replacement, existing valid chunks are not lost."""
    from unittest.mock import patch

    service = TranscriptChunkingService(db=db_session, config=ChunkingConfig(target_words=100))
    ep_id = sample_episode.id

    # Step 1: Initial successful chunking
    detail1 = service.process_episode(sample_episode, dry_run=False)
    assert detail1.status == "processed"
    initial_chunks = get_chunks_by_episode_id(db_session, ep_id)
    initial_count = len(initial_chunks)
    assert initial_count > 0
    initial_contents = [c.content for c in initial_chunks]

    # Step 2: Attempt update with new transcript content, but simulate DB write failure during insert
    sample_episode.content_checksum = "checksum_chesky_update_crash"
    sample_episode.transcript_text += "\n\nLenny (00:04:00):\nNew closing remarks."
    db_session.commit()

    with patch("backend.app.chunking.service.create_chunks", side_effect=RuntimeError("Simulated DB Error On Update")):
        detail2 = service.process_episode(sample_episode, dry_run=False)

    assert detail2.status == "failed"

    # Step 3: Transaction rollback must have restored the previous valid chunks
    persisted_chunks = get_chunks_by_episode_id(db_session, ep_id)
    assert len(persisted_chunks) == initial_count
    for c in persisted_chunks:
        assert c.source_checksum == "checksum_chesky_initial_12345"
    assert [c.content for c in persisted_chunks] == initial_contents

    # Parent episode remains persisted
    assert get_episode_by_id(db_session, ep_id) is not None


def test_rechunking_when_configuration_changes(db_session: Session, sample_episode: PodcastEpisode):
    """Verify that changing chunking configuration (e.g. target_words) triggers re-chunking."""
    cfg1 = ChunkingConfig(target_words=200, overlap_words=40)
    service1 = TranscriptChunkingService(db=db_session, config=cfg1)
    ep_id = sample_episode.id

    # Run 1: Initial chunking under cfg1
    detail1 = service1.process_episode(sample_episode, dry_run=False)
    assert detail1.status == "processed"
    assert detail1.config_fingerprint == cfg1.fingerprint()
    count_cfg1 = count_chunks_for_episode(db_session, ep_id)

    # Run 2: Re-run with identical config -> must be skipped
    detail2 = service1.process_episode(sample_episode, dry_run=False)
    assert detail2.status == "skipped"
    assert count_chunks_for_episode(db_session, ep_id) == count_cfg1

    # Run 3: Re-run with modified configuration -> must rebuild chunks
    cfg2 = ChunkingConfig(target_words=80, overlap_words=20)
    service2 = TranscriptChunkingService(db=db_session, config=cfg2)

    detail3 = service2.process_episode(sample_episode, dry_run=False)
    assert detail3.status == "updated"
    assert detail3.config_fingerprint == cfg2.fingerprint()

    updated_chunks = get_chunks_by_episode_id(db_session, ep_id)
    assert len(updated_chunks) == detail3.chunks_count
    for c in updated_chunks:
        assert c.config_fingerprint == cfg2.fingerprint()


def test_dry_run_performs_zero_database_writes(db_session: Session, sample_episode: PodcastEpisode):
    """Verify that dry-run mode computes chunk counts but writes zero records to PostgreSQL."""
    service = TranscriptChunkingService(db=db_session)
    report = service.chunk_all_episodes(dry_run=True)

    assert report.total_episodes_inspected == 1
    assert report.episodes_processed == 1
    assert report.dry_run is True
    assert report.total_chunks_created > 0

    # Database must remain empty
    assert count_chunks(db_session) == 0


# ---------------------------------------------------------------------------
# CLI Integration Tests
# ---------------------------------------------------------------------------

def test_chunking_cli_dry_run_workflow(db_session: Session, sample_episode: PodcastEpisode):
    """Verify that chunking CLI in dry-run mode previews chunking without persisting records."""
    import sys
    from unittest.mock import patch

    @contextmanager
    def mock_session_ctx():
        yield db_session

    with patch("backend.app.chunking.cli.get_db_session", side_effect=mock_session_ctx):
        with patch.object(sys, "argv", ["cli.py", "--dry-run", "--limit", "1"]):
            exit_code = cli.main()

    assert exit_code == 0
    assert count_chunks(db_session) == 0


def test_chunking_cli_unconfigured_database():
    """Verify that chunking CLI returns exit code 2 when database is unconfigured."""
    import sys
    from unittest.mock import patch

    @contextmanager
    def mock_unconfigured():
        raise DatabaseUnconfiguredException("Database not configured.")
        yield  # pragma: no cover

    with patch("backend.app.chunking.cli.get_db_session", side_effect=mock_unconfigured):
        with patch.object(sys, "argv", ["cli.py", "--dry-run"]):
            exit_code = cli.main()

    assert exit_code == 2


def test_chunking_cli_zero_episodes_found(db_session: Session):
    """Verify that chunking CLI returns exit code 1 when no episodes exist in the database."""
    import sys
    from unittest.mock import patch

    # Explicit isolation check: verify database is completely pristine
    assert count_episodes(db_session) == 0

    @contextmanager
    def mock_session_ctx():
        yield db_session

    with patch("backend.app.chunking.cli.get_db_session", side_effect=mock_session_ctx):
        with patch.object(sys, "argv", ["cli.py", "--dry-run"]):
            exit_code = cli.main()

    assert exit_code == 1
