"""Regression tests for transcript ingestion CLI and database session lifecycle."""

from contextlib import contextmanager
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.app.database import (
    DatabaseUnavailableException,
    DatabaseUnconfiguredException,
    get_db_session,
)
import backend.app.ingestion.cli as cli
from backend.app.repositories.episode_repository import count_episodes

SAMPLE_TRANSCRIPT_CONTENT = """---
guest: Test Guest
title: Test Episode Title
publish_date: 2024-01-15
---
# Transcript
[00:00:00] Lenny: Welcome to the test podcast!
"""


def test_cli_and_session_imports_cleanly():
    """Verify that CLI entrypoint and get_db_session import without any ImportError."""
    assert callable(get_db_session)
    assert callable(cli.main)
    assert callable(cli.build_parser)


def test_get_db_session_lifecycle_success():
    """Verify that get_db_session checkout verifies connection and guarantees session closure."""
    mock_session = MagicMock(spec=Session)
    mock_factory = MagicMock(return_value=mock_session)

    with patch("backend.app.database.get_session_factory", return_value=mock_factory):
        with get_db_session() as session:
            assert session is mock_session
            # Connection check SELECT 1 was executed on checkout
            mock_session.execute.assert_called_once()

        # Session was closed upon exiting context manager
        mock_session.close.assert_called_once()


def test_get_db_session_lifecycle_failure_guarantees_closure():
    """Verify that get_db_session guarantees session closure even when unhandled exceptions occur."""
    mock_session = MagicMock(spec=Session)
    mock_factory = MagicMock(return_value=mock_session)

    with patch("backend.app.database.get_session_factory", return_value=mock_factory):
        with pytest.raises(RuntimeError, match="Simulated worker crash"):
            with get_db_session():
                raise RuntimeError("Simulated worker crash")

        # Session must be closed regardless of exception
        mock_session.close.assert_called_once()


def test_get_db_session_unconfigured_raises_exception():
    """Verify that get_db_session raises DatabaseUnconfiguredException when factory is None."""
    with patch("backend.app.database.get_session_factory", return_value=None):
        with pytest.raises(DatabaseUnconfiguredException):
            with get_db_session():
                pass


def test_cli_main_dry_run_does_not_persist_changes(tmp_path: Path, db_session: Session):
    """Verify that CLI in --dry-run mode processes transcripts without persisting records to PostgreSQL."""
    # Setup sample transcript structure
    ep_dir = tmp_path / "episodes" / "test-guest"
    ep_dir.mkdir(parents=True)
    (ep_dir / "transcript.md").write_text(SAMPLE_TRANSCRIPT_CONTENT, encoding="utf-8")

    @contextmanager
    def mock_session_ctx():
        yield db_session

    with patch("backend.app.ingestion.cli.get_db_session", side_effect=mock_session_ctx):
        with patch.object(sys, "argv", ["cli.py", "--dir", str(tmp_path), "--dry-run"]):
            exit_code = cli.main()

    assert exit_code == 0
    # In dry-run mode, 0 episodes must be committed to the database
    assert count_episodes(db_session) == 0


def test_cli_main_missing_directory_returns_error(tmp_path: Path):
    """Verify that CLI returns exit code 1 when the specified directory does not exist."""
    missing_dir = tmp_path / "nonexistent_dir"
    with patch.object(sys, "argv", ["cli.py", "--dir", str(missing_dir), "--dry-run"]):
        exit_code = cli.main()

    assert exit_code == 1


def test_cli_main_database_unconfigured_returns_error(tmp_path: Path):
    """Verify that CLI handles unconfigured database with clean exit code 2."""
    corpus_dir = tmp_path / "episodes"
    corpus_dir.mkdir(parents=True)

    @contextmanager
    def mock_unconfigured_ctx():
        raise DatabaseUnconfiguredException("Database not configured.")
        yield  # pragma: no cover

    with patch("backend.app.ingestion.cli.get_db_session", side_effect=mock_unconfigured_ctx):
        with patch.object(sys, "argv", ["cli.py", "--dir", str(tmp_path)]):
            exit_code = cli.main()

    assert exit_code == 2


def test_cli_main_database_unavailable_returns_error(tmp_path: Path):
    """Verify that CLI handles database connection failure with clean exit code 2."""
    corpus_dir = tmp_path / "episodes"
    corpus_dir.mkdir(parents=True)

    @contextmanager
    def mock_unavailable_ctx():
        raise DatabaseUnavailableException("Connection refused.")
        yield  # pragma: no cover

    with patch("backend.app.ingestion.cli.get_db_session", side_effect=mock_unavailable_ctx):
        with patch.object(sys, "argv", ["cli.py", "--dir", str(tmp_path)]):
            exit_code = cli.main()

    assert exit_code == 2


def test_discovery_within_dot_local_parent_directory(tmp_path: Path, db_session: Session):
    """Verify that transcripts stored in paths containing '.local' (e.g. .local/corpus/...) are correctly discovered."""
    from backend.app.ingestion.service import TranscriptIngestionService

    # Specifically create a .local directory in the path hierarchy
    corpus_dir = tmp_path / ".local" / "corpus" / "lennys-podcast-transcripts"
    ep_dir = corpus_dir / "episodes" / "ada-chen-rekhi"
    ep_dir.mkdir(parents=True)
    (ep_dir / "transcript.md").write_text(SAMPLE_TRANSCRIPT_CONTENT, encoding="utf-8")

    service = TranscriptIngestionService(db=db_session)
    discovered = service.discover_transcript_files(corpus_dir)

    assert len(discovered) == 1
    assert discovered[0].name == "transcript.md"
    assert discovered[0].parent.name == "ada-chen-rekhi"


def test_cli_canonical_repository_layout_discovery_and_exclusion(tmp_path: Path, db_session: Session):
    """Verify that CLI discovers all episodes in canonical episodes/{slug}/transcript.md layout and excludes non-transcripts."""
    corpus_root = tmp_path / "lennys-podcast-transcripts"
    corpus_root.mkdir()

    # 1. Episode directories
    ep1 = corpus_root / "episodes" / "first-guest"
    ep1.mkdir(parents=True)
    (ep1 / "transcript.md").write_text(SAMPLE_TRANSCRIPT_CONTENT, encoding="utf-8")

    ep2 = corpus_root / "episodes" / "second-guest"
    ep2.mkdir(parents=True)
    (ep2 / "transcript.md").write_text(SAMPLE_TRANSCRIPT_CONTENT, encoding="utf-8")

    # 2. Excluded non-episode files and directories
    (corpus_root / "README.md").write_text("# Lenny Podcast Transcripts", encoding="utf-8")
    (corpus_root / "CLAUDE.md").write_text("# Repo Guide", encoding="utf-8")
    index_dir = corpus_root / "index"
    index_dir.mkdir()
    (index_dir / "topics.md").write_text("# Topic Index", encoding="utf-8")

    @contextmanager
    def mock_session_ctx():
        yield db_session

    with patch("backend.app.ingestion.cli.get_db_session", side_effect=mock_session_ctx):
        with patch.object(sys, "argv", ["cli.py", "--dir", str(corpus_root), "--dry-run"]):
            exit_code = cli.main()

    assert exit_code == 0
    # Dry-run must never write to database
    assert count_episodes(db_session) == 0


def test_cli_empty_directory_returns_error(tmp_path: Path, db_session: Session):
    """Verify that running CLI against a completely empty directory returns exit code 1 with error diagnostic."""
    empty_corpus = tmp_path / "empty_corpus"
    empty_corpus.mkdir()

    @contextmanager
    def mock_session_ctx():
        yield db_session

    with patch("backend.app.ingestion.cli.get_db_session", side_effect=mock_session_ctx):
        with patch.object(sys, "argv", ["cli.py", "--dir", str(empty_corpus), "--dry-run"]):
            exit_code = cli.main()

    assert exit_code == 1


def test_cli_unsupported_layout_returns_error(tmp_path: Path, db_session: Session):
    """Verify that running CLI against a directory without matching transcripts returns exit code 1."""
    invalid_layout = tmp_path / "invalid_layout"
    invalid_layout.mkdir()
    (invalid_layout / "some_notes.txt").write_text("not a transcript", encoding="utf-8")

    @contextmanager
    def mock_session_ctx():
        yield db_session

    with patch("backend.app.ingestion.cli.get_db_session", side_effect=mock_session_ctx):
        with patch.object(sys, "argv", ["cli.py", "--dir", str(invalid_layout), "--dry-run"]):
            exit_code = cli.main()

    assert exit_code == 1

