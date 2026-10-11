"""Service for idempotent podcast transcript chunking and database persistence."""

from dataclasses import dataclass, field
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.chunking.chunker import (
    ChunkingConfig,
    ChunkResult,
    chunk_transcript_text,
)
from backend.app.models.episode import PodcastEpisode
from backend.app.repositories.chunk_repository import (
    count_chunks_for_episode,
    create_chunks,
    delete_chunks_by_episode_id,
    get_chunk_checksum_and_fingerprint_for_episode,
    get_chunk_checksum_for_episode,
)

logger = logging.getLogger(__name__)


@dataclass
class EpisodeChunkingDetail:
    """Detail of a single episode's chunking outcome."""

    episode_id: uuid.UUID
    slug: str
    status: str  # 'processed', 'updated', 'skipped', 'failed'
    chunks_count: int = 0
    checksum: Optional[str] = None
    config_fingerprint: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ChunkingReport:
    """Consolidated summary report of a transcript chunking run."""

    total_episodes_inspected: int = 0
    episodes_processed: int = 0  # newly chunked
    episodes_updated: int = 0    # rebuilt due to checksum or config change or force
    episodes_skipped: int = 0    # already current
    failed_episodes: int = 0     # failures
    total_chunks_created: int = 0
    dry_run: bool = False
    duration_seconds: float = 0.0
    details: List[EpisodeChunkingDetail] = field(default_factory=list)

    def as_summary_dict(self) -> Dict[str, Any]:
        """Return structured summary dictionary suitable for logging and CLI display."""
        return {
            "total_episodes_inspected": self.total_episodes_inspected,
            "episodes_processed": self.episodes_processed,
            "episodes_updated": self.episodes_updated,
            "episodes_skipped": self.episodes_skipped,
            "failed_episodes": self.failed_episodes,
            "total_chunks_created": self.total_chunks_created,
            "dry_run": self.dry_run,
            "duration_seconds": round(self.duration_seconds, 2),
        }


class TranscriptChunkingService:
    """Service to split podcast transcripts into passages and persist them idempotently."""

    def __init__(self, db: Session, config: Optional[ChunkingConfig] = None):
        self.db = db
        self.config = config or ChunkingConfig()

    def process_episode(
        self,
        episode: PodcastEpisode,
        dry_run: bool = False,
        force: bool = False,
    ) -> EpisodeChunkingDetail:
        """Chunk a single episode and persist results idempotently."""
        # 1. Safely capture scalar values before any DB operations that could fail or rollback
        episode_id: uuid.UUID = episode.id
        episode_slug: str = episode.slug
        content_checksum: str = episode.content_checksum
        transcript_text: str = episode.transcript_text or ""

        # Phase 1: Inspection & chunk generation (Read-only operations)
        try:
            existing_checksum, existing_fingerprint = get_chunk_checksum_and_fingerprint_for_episode(
                self.db, episode_id
            )
            existing_count = count_chunks_for_episode(self.db, episode_id)
            current_fingerprint = self.config.fingerprint()

            # Idempotency check: skip only if chunks exist AND source checksum matches AND config fingerprint matches
            if (
                existing_count > 0
                and existing_checksum == content_checksum
                and existing_fingerprint == current_fingerprint
                and not force
            ):
                return EpisodeChunkingDetail(
                    episode_id=episode_id,
                    slug=episode_slug,
                    status="skipped",
                    chunks_count=existing_count,
                    checksum=existing_checksum,
                    config_fingerprint=existing_fingerprint,
                )

            # Generate chunks from transcript text
            chunk_results: List[ChunkResult] = chunk_transcript_text(
                transcript_text=transcript_text,
                config=self.config,
            )
        except Exception as read_exc:
            if self.db.is_active:
                try:
                    self.db.rollback()
                except Exception:
                    pass
            logger.exception("Failed inspecting or chunking episode '%s': %s", episode_slug, read_exc)
            return EpisodeChunkingDetail(
                episode_id=episode_id,
                slug=episode_slug,
                status="failed",
                error=str(read_exc),
            )

        is_update = existing_count > 0
        status = "updated" if is_update else "processed"

        # Phase 2: Atomic Persistence via SAVEPOINT
        if not dry_run:
            try:
                # ATOMIC PER-EPISODE SAVEPOINT:
                # Uses begin_nested() (SAVEPOINT) so that failures during chunk insertion
                # roll back ONLY the chunk operations for this episode, restoring previously
                # valid chunks (during an update) and preserving parent episode records.
                with self.db.begin_nested():
                    if is_update:
                        delete_chunks_by_episode_id(self.db, episode_id, commit=False)

                    # Prepare records for persistence
                    chunks_data = [
                        {
                            "episode_id": episode_id,
                            "chunk_index": cr.chunk_index,
                            "content": cr.content,
                            "word_count": cr.word_count,
                            "char_start": cr.char_start,
                            "char_end": cr.char_end,
                            "start_seconds": cr.start_seconds,
                            "end_seconds": cr.end_seconds,
                            "source_checksum": content_checksum,
                            "config_fingerprint": current_fingerprint,
                        }
                        for cr in chunk_results
                    ]

                    create_chunks(self.db, chunks_data, commit=False)
            except Exception as write_exc:
                # The savepoint rollback was executed automatically by the begin_nested() context manager.
                # DO NOT call self.db.rollback() here! An outer rollback would destroy the parent
                # episode, wipe out pre-existing valid chunks, and abort the surrounding transaction.
                logger.exception("Failed persisting chunks within savepoint for episode '%s': %s", episode_slug, write_exc)
                return EpisodeChunkingDetail(
                    episode_id=episode_id,
                    slug=episode_slug,
                    status="failed",
                    error=str(write_exc),
                )

            # Savepoint succeeded; commit outer transaction
            try:
                self.db.commit()
            except Exception as commit_exc:
                if self.db.is_active:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass
                logger.exception("Failed committing transaction for episode '%s': %s", episode_slug, commit_exc)
                return EpisodeChunkingDetail(
                    episode_id=episode_id,
                    slug=episode_slug,
                    status="failed",
                    error=str(commit_exc),
                )

        return EpisodeChunkingDetail(
            episode_id=episode_id,
            slug=episode_slug,
            status=status,
            chunks_count=len(chunk_results),
            checksum=content_checksum,
            config_fingerprint=current_fingerprint,
        )

    def chunk_all_episodes(
        self,
        limit: Optional[int] = None,
        slug: Optional[str] = None,
        dry_run: bool = False,
        force: bool = False,
    ) -> ChunkingReport:
        """Stream through podcast episodes in PostgreSQL and chunk them idempotently."""
        start_time = time.perf_counter()

        stmt = select(PodcastEpisode.id)
        if slug:
            stmt = stmt.where(PodcastEpisode.slug == slug)

        stmt = stmt.order_by(
            PodcastEpisode.publish_date.desc().nullslast(),
            PodcastEpisode.created_at.desc(),
        )

        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)

        episode_ids = list(self.db.scalars(stmt).all())

        report = ChunkingReport(
            total_episodes_inspected=len(episode_ids),
            dry_run=dry_run,
        )

        for ep_id in episode_ids:
            episode = self.db.get(PodcastEpisode, ep_id)
            if episode is None:
                continue

            detail = self.process_episode(episode, dry_run=dry_run, force=force)
            report.details.append(detail)

            if detail.status == "processed":
                report.episodes_processed += 1
                report.total_chunks_created += detail.chunks_count
            elif detail.status == "updated":
                report.episodes_updated += 1
                report.total_chunks_created += detail.chunks_count
            elif detail.status == "skipped":
                report.episodes_skipped += 1
            elif detail.status == "failed":
                report.failed_episodes += 1

        report.duration_seconds = time.perf_counter() - start_time
        logger.info(
            "Chunking run completed: %d episodes inspected in %.2fs (processed=%d, updated=%d, skipped=%d, failed=%d, dry_run=%s)",
            report.total_episodes_inspected,
            report.duration_seconds,
            report.episodes_processed,
            report.episodes_updated,
            report.episodes_skipped,
            report.failed_episodes,
            report.dry_run,
        )
        return report
