from datetime import date, datetime
import json
from pathlib import Path
import pytest
from sqlalchemy.orm import Session

from backend.app.ingestion.parser import (
    EmptyTranscriptError,
    ParsedTranscript,
    TranscriptParseError,
    compute_content_checksum,
    extract_video_id,
    make_json_serializable,
    parse_date,
    parse_transcript_content,
    parse_transcript_file,
)
from backend.app.ingestion.service import TranscriptIngestionService
from backend.app.models.episode import PodcastEpisode
from backend.app.repositories.episode_repository import (
    count_episodes,
    get_episode_by_slug,
    list_episodes,
)

# ---------------------------------------------------------------------------
# Synthetic Test Fixtures
# ---------------------------------------------------------------------------

SAMPLE_VALID_TRANSCRIPT = """---
guest: Elena Verna
title: "Elena Verna on Product-Led Growth, B2B Marketing, and Career Transitions"
publish_date: 2023-04-16
youtube_url: https://www.youtube.com/watch?v=dQw4w9WgXcQ
video_id: dQw4w9WgXcQ
description: Elena Verna is a growth advisor specializing in B2B product-led growth.
duration_seconds: 3720
tags:
  - PLG
  - B2B
  - Growth
---
# Transcript

[00:00:00] Lenny: Welcome to the podcast, Elena!
[00:00:05] Elena: Thank you so much for having me, Lenny.
[00:00:10] Lenny: Today we are talking about product-led growth in B2B SaaS.
"""

SAMPLE_MINIMAL_TRANSCRIPT = """---
title: Minimal Episode
---
This is a transcript with minimal metadata and no optional fields.
"""

SAMPLE_TRANSCRIPT_WITHOUT_FRONTMATTER = """# Raw Transcript Without Frontmatter
[00:00:00] Lenny: Just a raw conversation transcript.
"""

SAMPLE_MALFORMED_YAML = """---
guest: Elena Verna
title: "Broken YAML
publish_date: 2023-04-16
---
Some body text.
"""

SAMPLE_UNTERMINATED_FRONTMATTER = """---
guest: Unclosed Frontmatter
title: Missing closing dashes
There is no closing delimiter.
"""

SAMPLE_EMPTY_BODY = """---
guest: Ghost Speaker
title: Empty Body
---
"""

SAMPLE_MULTILINE_DESCRIPTION_WITH_INDENTED_DELIMITERS = """---
guest: Lulu Cheng Meservey
title: Gain attention as an underdog with this framework | Lulu Cheng Meservey
youtube_url: https://www.youtube.com/watch?v=qKXIBE7KRGo
video_id: qKXIBE7KRGo
publish_date: 2023-03-27
description: 'Lulu Cheng Meservey explains how to use the concentric circles framework
  to win the hearts and minds of your audience.

  🎙️Find the full episode here: https://youtu.be/LTSEOeKV_Hs


  —

  ...

  ---

  '
duration_seconds: 164.0
duration: '2:44'
view_count: 2507
channel: Lenny's Podcast
keywords:
- growth
- metrics
- okrs
- leadership
---
# Gain attention as an underdog with this framework | Lulu Cheng Meservey

## Transcript

[00:00:00] Lulu: I often say to find your audience's cultural erogenous zones.
"""


# ---------------------------------------------------------------------------
# Parser Unit Tests
# ---------------------------------------------------------------------------

def test_parse_multiline_description_with_indented_delimiters():
    """Verify that indented '...' and '---' inside multiline strings are not treated as document boundaries."""
    checksum = compute_content_checksum(SAMPLE_MULTILINE_DESCRIPTION_WITH_INDENTED_DELIMITERS.encode("utf-8"))
    parsed = parse_transcript_content(
        content=SAMPLE_MULTILINE_DESCRIPTION_WITH_INDENTED_DELIMITERS,
        fallback_slug="lulu-cheng-meservey",
        checksum=checksum,
        source_path="episodes/lulu-cheng-meservey/transcript.md",
    )

    assert parsed.slug == "lulu-cheng-meservey"
    assert parsed.guest_name == "Lulu Cheng Meservey"
    assert parsed.title == "Gain attention as an underdog with this framework | Lulu Cheng Meservey"
    assert parsed.publish_date == date(2023, 3, 27)
    assert parsed.youtube_url == "https://www.youtube.com/watch?v=qKXIBE7KRGo"
    assert parsed.video_id == "qKXIBE7KRGo"
    # Indented '...' and '---' preserved within description string
    assert "concentric circles framework" in parsed.description
    assert "..." in parsed.description
    assert "---" in parsed.description
    # Trailing fields after multiline string must be fully extracted
    assert parsed.raw_metadata["duration_seconds"] == 164.0
    assert parsed.raw_metadata["keywords"] == ["growth", "metrics", "okrs", "leadership"]
    # Body text must be preserved accurately
    assert "[00:00:00] Lulu: I often say to find your audience" in parsed.transcript_text


def test_parse_valid_transcript_with_full_frontmatter():
    """Verify that a full YAML frontmatter transcript parses all fields accurately."""
    checksum = compute_content_checksum(SAMPLE_VALID_TRANSCRIPT.encode("utf-8"))
    parsed = parse_transcript_content(
        content=SAMPLE_VALID_TRANSCRIPT,
        fallback_slug="elena-verna",
        checksum=checksum,
        source_path="episodes/elena-verna/transcript.md",
    )

    assert parsed.slug == "elena-verna"
    assert parsed.guest_name == "Elena Verna"
    assert parsed.title == "Elena Verna on Product-Led Growth, B2B Marketing, and Career Transitions"
    assert parsed.publish_date == date(2023, 4, 16)
    assert parsed.youtube_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert parsed.video_id == "dQw4w9WgXcQ"
    assert "Elena Verna is a growth advisor" in parsed.description
    assert "[00:00:00] Lenny: Welcome to the podcast, Elena!" in parsed.transcript_text
    assert parsed.content_checksum == checksum
    assert parsed.source_path == "episodes/elena-verna/transcript.md"
    assert parsed.raw_metadata["duration_seconds"] == 3720
    assert "PLG" in parsed.raw_metadata["tags"]


def test_parse_missing_optional_metadata():
    """Verify safe defaults when optional metadata fields are missing."""
    checksum = compute_content_checksum(SAMPLE_MINIMAL_TRANSCRIPT.encode("utf-8"))
    parsed = parse_transcript_content(
        content=SAMPLE_MINIMAL_TRANSCRIPT,
        fallback_slug="minimal-episode",
        checksum=checksum,
    )

    assert parsed.slug == "minimal-episode"
    assert parsed.guest_name is None
    assert parsed.title == "Minimal Episode"
    assert parsed.publish_date is None
    assert parsed.youtube_url is None
    assert parsed.video_id is None
    assert parsed.description is None
    assert "This is a transcript with minimal metadata" in parsed.transcript_text


def test_parse_transcript_without_frontmatter():
    """Verify that files lacking frontmatter are treated entirely as transcript body."""
    checksum = compute_content_checksum(SAMPLE_TRANSCRIPT_WITHOUT_FRONTMATTER.encode("utf-8"))
    parsed = parse_transcript_content(
        content=SAMPLE_TRANSCRIPT_WITHOUT_FRONTMATTER,
        fallback_slug="raw-episode",
        checksum=checksum,
    )

    assert parsed.slug == "raw-episode"
    assert parsed.guest_name is None
    assert parsed.title == "Raw Episode"
    assert "Just a raw conversation transcript" in parsed.transcript_text
    assert parsed.raw_metadata == {}


def test_parse_malformed_yaml_raises_error():
    """Verify that invalid YAML frontmatter raises TranscriptParseError."""
    checksum = compute_content_checksum(SAMPLE_MALFORMED_YAML.encode("utf-8"))
    with pytest.raises(TranscriptParseError) as exc_info:
        parse_transcript_content(
            content=SAMPLE_MALFORMED_YAML,
            fallback_slug="malformed",
            checksum=checksum,
        )
    assert "Malformed YAML" in str(exc_info.value)


def test_parse_unterminated_frontmatter_raises_error():
    """Verify that missing closing frontmatter delimiter raises TranscriptParseError."""
    checksum = compute_content_checksum(SAMPLE_UNTERMINATED_FRONTMATTER.encode("utf-8"))
    with pytest.raises(TranscriptParseError) as exc_info:
        parse_transcript_content(
            content=SAMPLE_UNTERMINATED_FRONTMATTER,
            fallback_slug="unterminated",
            checksum=checksum,
        )
    assert "Unterminated YAML frontmatter" in str(exc_info.value)


def test_parse_empty_transcript_raises_error():
    """Verify that empty files or files with empty transcript text raise EmptyTranscriptError."""
    # 1. Completely empty string
    with pytest.raises(EmptyTranscriptError):
        parse_transcript_content(content="", fallback_slug="empty", checksum="abc")

    # 2. Whitespace only
    with pytest.raises(EmptyTranscriptError):
        parse_transcript_content(content="   \n\t  ", fallback_slug="empty", checksum="abc")

    # 3. Frontmatter present but empty body
    with pytest.raises(EmptyTranscriptError):
        parse_transcript_content(content=SAMPLE_EMPTY_BODY, fallback_slug="empty-body", checksum="abc")


def test_content_checksum_consistency_and_sensitivity():
    """Verify that checksums are deterministic and sensitive to content changes."""
    content_a = b"First transcript content"
    content_b = b"First transcript content"
    content_c = b"First transcript content with one letter change"

    hash_a = compute_content_checksum(content_a)
    hash_b = compute_content_checksum(content_b)
    hash_c = compute_content_checksum(content_c)

    assert hash_a == hash_b
    assert hash_a != hash_c
    assert len(hash_a) == 64


def test_date_parsing_various_formats():
    """Verify date parsing handles date, datetime, ISO string, and invalid values."""
    assert parse_date(date(2023, 5, 20)) == date(2023, 5, 20)
    assert parse_date("2023-05-20") == date(2023, 5, 20)
    assert parse_date("2023-05-20T14:30:00Z") == date(2023, 5, 20)
    assert parse_date("2023/05/20") == date(2023, 5, 20)
    assert parse_date("") is None
    assert parse_date("not-a-date") is None
    assert parse_date(None) is None


def test_video_id_extraction():
    """Verify extraction of 11-character YouTube video IDs from various URL formats."""
    assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s") == "dQw4w9WgXcQ"
    assert extract_video_id(None) is None
    assert extract_video_id("invalid") is None


# ---------------------------------------------------------------------------
# Ingestion Service Unit Tests
# ---------------------------------------------------------------------------

def test_discover_transcript_files_filtering(tmp_path: Path, db_session: Session):
    """Verify discovery only picks episode transcripts and ignores index, scripts, guides."""
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()

    # 1. Valid episode directories
    ep1 = corpus_dir / "episodes" / "brian-chesky"
    ep1.mkdir(parents=True)
    (ep1 / "transcript.md").write_text(SAMPLE_VALID_TRANSCRIPT, encoding="utf-8")

    ep2 = corpus_dir / "episodes" / "shreyas-doshi"
    ep2.mkdir(parents=True)
    (ep2 / "transcript.md").write_text(SAMPLE_MINIMAL_TRANSCRIPT, encoding="utf-8")

    # 2. Excluded directories and files
    index_dir = corpus_dir / "index"
    index_dir.mkdir()
    (index_dir / "topics.md").write_text("# Topic Index", encoding="utf-8")

    scripts_dir = corpus_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "scrape.py").write_text("print('script')", encoding="utf-8")

    # 3. Root guide files
    (corpus_dir / "README.md").write_text("# Repository Readme", encoding="utf-8")
    (corpus_dir / "CLAUDE.md").write_text("# Claude instructions", encoding="utf-8")

    service = TranscriptIngestionService(db=db_session)
    discovered = service.discover_transcript_files(corpus_dir)

    assert len(discovered) == 2
    slugs = {p.parent.name for p in discovered}
    assert slugs == {"brian-chesky", "shreyas-doshi"}


def test_ingestion_dry_run_does_not_modify_database(tmp_path: Path, db_session: Session):
    """Verify that dry-run reports planned imports without writing records to PostgreSQL."""
    corpus_dir = tmp_path / "corpus"
    ep_dir = corpus_dir / "episodes" / "elena-verna"
    ep_dir.mkdir(parents=True)
    (ep_dir / "transcript.md").write_text(SAMPLE_VALID_TRANSCRIPT, encoding="utf-8")

    service = TranscriptIngestionService(db=db_session)

    # Execute with dry_run=True
    report = service.ingest_directory(corpus_dir, dry_run=True)

    assert report.total_files_discovered == 1
    assert report.imported == 1
    assert report.dry_run is True

    # Database must remain empty
    assert count_episodes(db_session) == 0
    assert get_episode_by_slug(db_session, "elena-verna") is None


def test_ingestion_creates_and_skips_unchanged_episodes(tmp_path: Path, db_session: Session):
    """Verify idempotent behavior: new files are imported; re-runs skip identical checksums."""
    corpus_dir = tmp_path / "corpus"
    ep1 = corpus_dir / "episodes" / "elena-verna"
    ep1.mkdir(parents=True)
    (ep1 / "transcript.md").write_text(SAMPLE_VALID_TRANSCRIPT, encoding="utf-8")

    ep2 = corpus_dir / "episodes" / "minimal-ep"
    ep2.mkdir(parents=True)
    (ep2 / "transcript.md").write_text(SAMPLE_MINIMAL_TRANSCRIPT, encoding="utf-8")

    service = TranscriptIngestionService(db=db_session)

    # Run 1: Initial ingestion
    report1 = service.ingest_directory(corpus_dir, dry_run=False)
    assert report1.total_files_discovered == 2
    assert report1.imported == 2
    assert report1.skipped == 0
    assert count_episodes(db_session) == 2

    # Assert dedicated SQL DATE column and raw_metadata JSON serialization
    ep1_record = get_episode_by_slug(db_session, "elena-verna")
    assert ep1_record is not None
    assert ep1_record.publish_date == date(2023, 4, 16)
    assert isinstance(ep1_record.publish_date, date)
    assert ep1_record.raw_metadata["publish_date"] == "2023-04-16"
    assert isinstance(ep1_record.raw_metadata["publish_date"], str)
    assert json.dumps(ep1_record.raw_metadata) is not None

    # Run 2: Exact re-run with unchanged files
    report2 = service.ingest_directory(corpus_dir, dry_run=False)
    assert report2.total_files_discovered == 2
    assert report2.imported == 0
    assert report2.skipped == 2
    assert count_episodes(db_session) == 2


def test_ingestion_updates_modified_episode_without_duplicates(tmp_path: Path, db_session: Session):
    """Verify that updating an existing transcript file modifies the record without creating duplicates."""
    corpus_dir = tmp_path / "corpus"
    ep_dir = corpus_dir / "episodes" / "elena-verna"
    ep_dir.mkdir(parents=True)
    transcript_file = ep_dir / "transcript.md"
    transcript_file.write_text(SAMPLE_VALID_TRANSCRIPT, encoding="utf-8")

    service = TranscriptIngestionService(db=db_session)

    # 1. First ingestion
    report1 = service.ingest_directory(corpus_dir, dry_run=False)
    assert report1.imported == 1

    initial_record = get_episode_by_slug(db_session, "elena-verna")
    assert initial_record is not None

    # Capture immutable snapshots of initial values before second ingestion to avoid
    # in-place mutation aliasing via SQLAlchemy's identity map on the shared session
    original_id = initial_record.id
    original_checksum = initial_record.content_checksum
    original_text = initial_record.transcript_text

    # 2. Modify the file content (simulate upstream transcript correction)
    updated_content = SAMPLE_VALID_TRANSCRIPT + "\n[00:00:15] Lenny: One more question about retention.\n"
    transcript_file.write_text(updated_content, encoding="utf-8")

    # 3. Second ingestion
    report2 = service.ingest_directory(corpus_dir, dry_run=False)
    assert report2.updated == 1
    assert report2.imported == 0
    assert report2.skipped == 0
    assert report2.failed == 0

    # Total records must still be 1 (no duplicate row created)
    assert count_episodes(db_session) == 1

    # Clear identity map cache to ensure fresh database retrieval
    db_session.expire_all()
    updated_record = get_episode_by_slug(db_session, "elena-verna")
    assert updated_record is not None

    # Verify ID is preserved, while checksum and text reflect the updated content
    assert updated_record.id == original_id
    assert updated_record.content_checksum != original_checksum
    assert updated_record.transcript_text != original_text
    assert "One more question about retention" in updated_record.transcript_text

    # 4. Re-ingesting unchanged updated file produces a skip
    report3 = service.ingest_directory(corpus_dir, dry_run=False)
    assert report3.total_files_discovered == 1
    assert report3.imported == 0
    assert report3.updated == 0
    assert report3.skipped == 1
    assert report3.failed == 0
    assert count_episodes(db_session) == 1



def test_ingestion_handles_malformed_files_without_aborting_batch(tmp_path: Path, db_session: Session):
    """Verify that a malformed file is recorded as failed while valid files in the batch succeed."""
    corpus_dir = tmp_path / "corpus"

    # Valid file
    ep_good = corpus_dir / "episodes" / "good-ep"
    ep_good.mkdir(parents=True)
    (ep_good / "transcript.md").write_text(SAMPLE_VALID_TRANSCRIPT, encoding="utf-8")

    # Broken YAML file
    ep_bad = corpus_dir / "episodes" / "bad-ep"
    ep_bad.mkdir(parents=True)
    (ep_bad / "transcript.md").write_text(SAMPLE_MALFORMED_YAML, encoding="utf-8")

    # Empty file
    ep_empty = corpus_dir / "episodes" / "empty-ep"
    ep_empty.mkdir(parents=True)
    (ep_empty / "transcript.md").write_text("", encoding="utf-8")

    service = TranscriptIngestionService(db=db_session)
    report = service.ingest_directory(corpus_dir, dry_run=False)

    assert report.total_files_discovered == 3
    assert report.imported == 1
    assert report.failed == 2
    assert count_episodes(db_session) == 1
    assert get_episode_by_slug(db_session, "good-ep") is not None


def test_nested_metadata_json_serializability():
    """Verify that YAML frontmatter with nested dates and timestamps is fully JSON-serializable."""
    frontmatter_nested = """---
guest: Advanced Guest
title: "Episode with Complex Metadata"
publish_date: 2023-04-16
schedule:
  recorded_at: 2023-04-10
  air_date: 2023-04-16
timeline:
  - milestone: recorded
    date: 2023-04-10
  - milestone: edited
    date: 2023-04-12
---
# Transcript Content
[00:00:00] Lenny: Welcome!
"""
    checksum = compute_content_checksum(frontmatter_nested.encode("utf-8"))
    parsed = parse_transcript_content(
        content=frontmatter_nested,
        fallback_slug="complex-ep",
        checksum=checksum,
    )

    # Dedicated SQL column preserves proper date object
    assert parsed.publish_date == date(2023, 4, 16)
    assert isinstance(parsed.publish_date, date)

    # raw_metadata must be completely JSON-serializable
    serialized = json.dumps(parsed.raw_metadata)
    assert serialized is not None

    # Nested date fields must be converted to ISO strings
    assert parsed.raw_metadata["publish_date"] == "2023-04-16"
    assert parsed.raw_metadata["schedule"]["recorded_at"] == "2023-04-10"
    assert parsed.raw_metadata["schedule"]["air_date"] == "2023-04-16"
    assert parsed.raw_metadata["timeline"][0]["date"] == "2023-04-10"
    assert parsed.raw_metadata["timeline"][1]["date"] == "2023-04-12"


def test_ingestion_recovers_session_after_database_error(tmp_path: Path, db_session: Session):
    """Verify that an unexpected database write error triggers a rollback and does not block subsequent imports."""
    from unittest.mock import patch

    corpus_dir = tmp_path / "corpus"

    # File 1: will fail during insert
    ep1 = corpus_dir / "episodes" / "fail-first"
    ep1.mkdir(parents=True)
    (ep1 / "transcript.md").write_text(SAMPLE_VALID_TRANSCRIPT, encoding="utf-8")

    # File 2: valid file that should succeed afterwards
    ep2 = corpus_dir / "episodes" / "succeed-second"
    ep2.mkdir(parents=True)
    (ep2 / "transcript.md").write_text(SAMPLE_MINIMAL_TRANSCRIPT, encoding="utf-8")

    service = TranscriptIngestionService(db=db_session)
    original_create = service.ingest_single_file

    def flaky_create(file_path, **kwargs):
        if "fail-first" in str(file_path):
            with patch("backend.app.ingestion.service.create_episode", side_effect=RuntimeError("Simulated DB Disk Glitch")):
                return original_create(file_path, **kwargs)
        return original_create(file_path, **kwargs)

    with patch.object(service, "ingest_single_file", side_effect=flaky_create):
        report = service.ingest_directory(corpus_dir, dry_run=False)

    assert report.total_files_discovered == 2
    assert report.failed == 1
    assert report.imported == 1
    assert count_episodes(db_session) == 1
    assert get_episode_by_slug(db_session, "succeed-second") is not None

