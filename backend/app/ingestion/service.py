"""Ingestion service for discovering, parsing, and persisting Lenny's Podcast transcripts."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from backend.app.ingestion.parser import (
    ParsedTranscript,
    TranscriptIngestionError,
    parse_transcript_file,
)
from backend.app.models.episode import PodcastEpisode
from backend.app.repositories.episode_repository import (
    create_episode,
    get_episode_by_slug,
    update_episode,
)

logger = logging.getLogger(__name__)

# Directories to skip when scanning for episode transcripts
EXCLUDED_DIRECTORIES: Set[str] = {
    "index",
    "scripts",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    ".git",
    ".github",
}

# Documentation and utility markdown files to ignore
EXCLUDED_FILENAMES: Set[str] = {
    "readme.md",
    "claude.md",
    "contributing.md",
    "license.md",
    "license",
    "index.md",
    "summary.md",
    "changelog.md",
}


@dataclass
class EpisodeIngestionDetail:
    """Detail for an individual episode file ingestion outcome."""

    file_path: str
    slug: str
    status: str  # 'imported', 'updated', 'skipped', 'failed'
    title: Optional[str] = None
    checksum: Optional[str] = None
    error: Optional[str] = None


@dataclass
class IngestionReport:
    """Consolidated summary report of a transcript ingestion run."""

    total_files_discovered: int = 0
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    dry_run: bool = False
    duration_seconds: float = 0.0
    details: List[EpisodeIngestionDetail] = field(default_factory=list)

    def as_summary_dict(self) -> Dict[str, Any]:
        """Return a structured dictionary suitable for logging or CLI output."""
        return {
            "total_files_discovered": self.total_files_discovered,
            "imported": self.imported,
            "updated": self.updated,
            "skipped": self.skipped,
            "failed": self.failed,
            "dry_run": self.dry_run,
            "duration_seconds": round(self.duration_seconds, 2),
        }


class TranscriptIngestionService:
    """Service to discover and ingest podcast transcripts into PostgreSQL idempotently."""

    def __init__(self, db: Session):
        self.db = db

    def discover_transcript_files(self, source_dir: Path) -> List[Path]:
        """Scan directory and return valid episode transcript markdown files.

        Recognizes canonical repository layout (episodes/{slug}/transcript.md)
        as well as flat or custom episode directories.
        Strictly filters out index directories, utility scripts, and repository guides.
        """
        if not source_dir.exists() or not source_dir.is_dir():
            logger.warning("Transcript source directory does not exist: %s", source_dir)
            return []

        resolved_source = source_dir.resolve()

        # If an 'episodes' subdirectory exists, target it specifically
        episodes_dir = resolved_source / "episodes"
        scan_root = episodes_dir if episodes_dir.is_dir() else resolved_source

        discovered: List[Path] = []
        for path in scan_root.rglob("*.md"):
            # 1. Skip non-files or hidden files
            if not path.is_file() or path.name.startswith("."):
                continue

            # 2. Skip excluded filenames (README.md, CLAUDE.md, etc.)
            if path.name.lower() in EXCLUDED_FILENAMES:
                continue

            # 3. Check directory exclusions ONLY relative to resolved_source (never workspace parent directories)
            try:
                rel_parts = {part.lower() for part in path.relative_to(resolved_source).parent.parts}
            except ValueError:
                rel_parts = {part.lower() for part in path.parent.parts}

            if rel_parts.intersection(EXCLUDED_DIRECTORIES):
                continue

            discovered.append(path)

        # Sort paths for deterministic ingestion order
        discovered.sort()
        return discovered

    def ingest_single_file(
        self,
        file_path: Path,
        source_root: Optional[Path] = None,
        dry_run: bool = False,
        force: bool = False,
    ) -> EpisodeIngestionDetail:
        """Parse and ingest or update a single episode file."""
        relative_path = (
            file_path.relative_to(source_root).as_posix()
            if source_root
            else file_path.as_posix()
        )

        try:
            parsed: ParsedTranscript = parse_transcript_file(
                file_path=file_path,
                relative_to=source_root,
            )
        except TranscriptIngestionError as err:
            logger.warning("Failed parsing transcript %s: %s", file_path.name, err)
            return EpisodeIngestionDetail(
                file_path=relative_path,
                slug=file_path.stem,
                status="failed",
                error=str(err),
            )
        except Exception as exc:
            logger.error("Unexpected error parsing %s: %s", file_path.name, exc)
            return EpisodeIngestionDetail(
                file_path=relative_path,
                slug=file_path.stem,
                status="failed",
                error=f"Unexpected parsing exception: {exc}",
            )

        # Check existing record in PostgreSQL
        existing = get_episode_by_slug(self.db, parsed.slug)

        if existing is not None:
            # Checksum match -> unchanged, skip
            if not force and existing.content_checksum == parsed.content_checksum:
                return EpisodeIngestionDetail(
                    file_path=relative_path,
                    slug=parsed.slug,
                    status="skipped",
                    title=existing.title,
                    checksum=existing.content_checksum,
                )

            # Checksum changed -> update existing episode without creating duplicates
            if not dry_run:
                try:
                    update_episode(
                        self.db,
                        episode=existing,
                        update_data={
                            "guest_name": parsed.guest_name,
                            "title": parsed.title,
                            "publish_date": parsed.publish_date,
                            "youtube_url": parsed.youtube_url,
                            "video_id": parsed.video_id,
                            "source_path": parsed.source_path,
                            "description": parsed.description,
                            "transcript_text": parsed.transcript_text,
                            "content_checksum": parsed.content_checksum,
                            "raw_metadata": parsed.raw_metadata,
                        },
                    )
                except Exception as exc:
                    self.db.rollback()
                    logger.error("Database update failed for %s: %s", parsed.slug, exc)
                    return EpisodeIngestionDetail(
                        file_path=relative_path,
                        slug=parsed.slug,
                        status="failed",
                        title=parsed.title,
                        error=f"Database update failed: {exc}",
                    )

            return EpisodeIngestionDetail(
                file_path=relative_path,
                slug=parsed.slug,
                status="updated",
                title=parsed.title,
                checksum=parsed.content_checksum,
            )

        # New episode -> insert into database
        if not dry_run:
            try:
                create_episode(
                    self.db,
                    episode_data={
                        "slug": parsed.slug,
                        "guest_name": parsed.guest_name,
                        "title": parsed.title,
                        "publish_date": parsed.publish_date,
                        "youtube_url": parsed.youtube_url,
                        "video_id": parsed.video_id,
                        "source_path": parsed.source_path,
                        "description": parsed.description,
                        "transcript_text": parsed.transcript_text,
                        "content_checksum": parsed.content_checksum,
                        "raw_metadata": parsed.raw_metadata,
                    },
                )
            except Exception as exc:
                self.db.rollback()
                logger.error("Database insert failed for %s: %s", parsed.slug, exc)
                return EpisodeIngestionDetail(
                    file_path=relative_path,
                    slug=parsed.slug,
                    status="failed",
                    title=parsed.title,
                    error=f"Database insert failed: {exc}",
                )

        return EpisodeIngestionDetail(
            file_path=relative_path,
            slug=parsed.slug,
            status="imported",
            title=parsed.title,
            checksum=parsed.content_checksum,
        )

    def ingest_directory(
        self,
        source_dir: Path,
        dry_run: bool = False,
        force: bool = False,
    ) -> IngestionReport:
        """Scan, discover, and ingest all transcript files from the specified directory.

        Operates in stream fashion to avoid loading the entire dataset into memory simultaneously.
        """
        start_time = time.perf_counter()
        files = self.discover_transcript_files(source_dir)

        report = IngestionReport(
            total_files_discovered=len(files),
            dry_run=dry_run,
        )

        for file_path in files:
            detail = self.ingest_single_file(
                file_path=file_path,
                source_root=source_dir,
                dry_run=dry_run,
                force=force,
            )
            report.details.append(detail)

            if detail.status == "imported":
                report.imported += 1
            elif detail.status == "updated":
                report.updated += 1
            elif detail.status == "skipped":
                report.skipped += 1
            elif detail.status == "failed":
                report.failed += 1

        report.duration_seconds = time.perf_counter() - start_time
        logger.info(
            "Ingestion completed: %s files in %.2fs (imported=%d, updated=%d, skipped=%d, failed=%d, dry_run=%s)",
            report.total_files_discovered,
            report.duration_seconds,
            report.imported,
            report.updated,
            report.skipped,
            report.failed,
            report.dry_run,
        )
        return report
