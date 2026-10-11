"""Service for idempotent, resource-efficient podcast transcript chunk vector embedding."""

from dataclasses import dataclass, field
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.embeddings.client import (
    DEFAULT_DOC_PREFIX,
    EmbeddingError,
    OllamaEmbeddingClient,
)
from backend.app.models.chunk import TranscriptChunk
from backend.app.models.embedding import TranscriptEmbedding
from backend.app.models.episode import PodcastEpisode
from backend.app.repositories.embedding_repository import (
    count_embeddings,
    create_or_update_embeddings_batch,
    get_existing_embeddings_metadata_for_chunk_ids,
)

logger = logging.getLogger(__name__)

MAX_ALLOWED_BATCH_SIZE: int = 32
DEFAULT_BATCH_SIZE: int = 4


def compute_embedding_input_checksum(text: str, prefix: str = DEFAULT_DOC_PREFIX) -> str:
    """Compute deterministic SHA-256 checksum of the text submitted for embedding."""
    full_input = f"{prefix}{text}" if not text.startswith(prefix) else text
    return hashlib.sha256(full_input.encode("utf-8")).hexdigest()


@dataclass
class EmbeddingReport:
    """Consolidated summary report of an embedding generation run."""

    total_chunks_inspected: int = 0
    chunks_embedded: int = 0     # Newly generated embeddings
    chunks_updated: int = 0      # Regenerated due to text/model change or force
    chunks_skipped: int = 0      # Already current (matching model + checksum)
    chunks_failed: int = 0       # Failed generation or persistence
    dry_run: bool = False
    duration_seconds: float = 0.0
    model_name: str = "nomic-embed-text"
    batch_size: int = DEFAULT_BATCH_SIZE
    error_summary: Optional[str] = None

    def as_summary_dict(self) -> Dict[str, Any]:
        """Return structured summary dictionary suitable for logging and CLI display."""
        return {
            "total_chunks_inspected": self.total_chunks_inspected,
            "chunks_embedded": self.chunks_embedded,
            "chunks_updated": self.chunks_updated,
            "chunks_skipped": self.chunks_skipped,
            "chunks_failed": self.chunks_failed,
            "dry_run": self.dry_run,
            "duration_seconds": round(self.duration_seconds, 2),
            "model_name": self.model_name,
            "batch_size": self.batch_size,
            "error_summary": self.error_summary,
        }


class TranscriptEmbeddingService:
    """Service to generate and store 768-D vector embeddings for transcript chunks idempotently."""

    def __init__(
        self,
        db: Session,
        client: Optional[OllamaEmbeddingClient] = None,
        doc_prefix: str = DEFAULT_DOC_PREFIX,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        self.db = db
        settings = get_settings()

        self.client = client or OllamaEmbeddingClient(
            base_url=settings.ollama_base_url,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout_seconds=float(settings.embedding_timeout_seconds),
            max_retries=settings.embedding_max_retries,
        )
        self.doc_prefix = doc_prefix

        # Enforce conservative batch size bounds to protect 8 GB RAM
        if batch_size < 1:
            self.batch_size = 1
        elif batch_size > MAX_ALLOWED_BATCH_SIZE:
            logger.warning(
                "Requested batch_size %d exceeds upper bound %d; capping at %d.",
                batch_size,
                MAX_ALLOWED_BATCH_SIZE,
                MAX_ALLOWED_BATCH_SIZE,
            )
            self.batch_size = MAX_ALLOWED_BATCH_SIZE
        else:
            self.batch_size = batch_size

    def embed_chunks(
        self,
        limit: Optional[int] = None,
        episode_slug: Optional[str] = None,
        dry_run: bool = False,
        force: bool = False,
        max_errors: Optional[int] = 10,
    ) -> EmbeddingReport:
        """Process transcript chunks in small, bounded batches and persist embeddings idempotently.

        Args:
            limit: Maximum number of chunks to process (None for all).
            episode_slug: Filter chunks to a single episode by slug (None for all).
            dry_run: When True, inspect pending work without calling Ollama or modifying the DB.
            force: When True, regenerate embeddings even if checksum and model match.
            max_errors: Maximum allowable chunk errors before stopping (None for unlimited).

        Returns:
            EmbeddingReport summarizing inspected, generated, updated, skipped, and failed counts.
        """
        start_time = time.perf_counter()

        report = EmbeddingReport(
            dry_run=dry_run,
            model_name=self.client.model,
            batch_size=self.batch_size,
        )

        # 1. Build deterministic query for chunk IDs
        stmt = (
            select(TranscriptChunk.id)
            .join(PodcastEpisode, TranscriptChunk.episode_id == PodcastEpisode.id)
        )

        if episode_slug:
            stmt = stmt.where(PodcastEpisode.slug == episode_slug)

        stmt = stmt.order_by(
            PodcastEpisode.publish_date.desc().nullslast(),
            PodcastEpisode.created_at.desc(),
            TranscriptChunk.chunk_index.asc(),
        )

        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)

        chunk_ids: List[uuid.UUID] = list(self.db.scalars(stmt).all())
        report.total_chunks_inspected = len(chunk_ids)

        if not chunk_ids:
            report.duration_seconds = time.perf_counter() - start_time
            return report

        # 2. Iterate through chunk IDs in small, bounded batches
        for i in range(0, len(chunk_ids), self.batch_size):
            if max_errors is not None and report.chunks_failed >= max_errors:
                msg = f"Embedding stopped: error threshold ({max_errors}) reached."
                logger.error(msg)
                report.error_summary = msg
                break

            batch_ids = chunk_ids[i : i + self.batch_size]

            # Fetch the actual chunk records for this batch only
            batch_stmt = (
                select(TranscriptChunk)
                .where(TranscriptChunk.id.in_(batch_ids))
                .order_by(TranscriptChunk.chunk_index.asc())
            )
            chunks: List[TranscriptChunk] = list(self.db.scalars(batch_stmt).all())

            # Query existing embedding metadata for this batch (model + checksum)
            existing_meta_map = get_existing_embeddings_metadata_for_chunk_ids(
                self.db, [c.id for c in chunks]
            )

            chunks_to_embed: List[TranscriptChunk] = []
            is_update_flags: List[bool] = []
            checksums_to_save: List[str] = []

            for chunk in chunks:
                input_checksum = compute_embedding_input_checksum(
                    chunk.content, prefix=self.doc_prefix
                )
                existing = existing_meta_map.get(chunk.id)

                if existing and not force:
                    existing_model, existing_checksum = existing
                    if (
                        existing_model == self.client.model
                        and existing_checksum == input_checksum
                    ):
                        report.chunks_skipped += 1
                        continue

                # Needs generation
                chunks_to_embed.append(chunk)
                is_update = existing is not None
                is_update_flags.append(is_update)
                checksums_to_save.append(input_checksum)

            if not chunks_to_embed:
                continue

            if dry_run:
                # Dry run: record would-process counts without network or DB writes
                for is_upd in is_update_flags:
                    if is_upd:
                        report.chunks_updated += 1
                    else:
                        report.chunks_embedded += 1
                continue

            # 3. Call Ollama for this batch
            try:
                texts = [c.content for c in chunks_to_embed]
                vectors = self.client.embed_texts(texts, prefix=self.doc_prefix)
            except Exception as embed_exc:
                logger.error(
                    "Ollama embedding failed for batch of %d chunks: %s",
                    len(chunks_to_embed),
                    embed_exc,
                )
                report.chunks_failed += len(chunks_to_embed)
                continue

            # 4. Atomic database persistence per batch via SAVEPOINT
            try:
                with self.db.begin_nested():
                    items_to_save = [
                        {
                            "chunk_id": chunk.id,
                            "embedding": vec,
                            "model_name": self.client.model,
                            "input_checksum": chk,
                        }
                        for chunk, vec, chk in zip(
                            chunks_to_embed, vectors, checksums_to_save
                        )
                    ]
                    create_or_update_embeddings_batch(
                        self.db, items_to_save, commit=False
                    )

                self.db.commit()

                for is_upd in is_update_flags:
                    if is_upd:
                        report.chunks_updated += 1
                    else:
                        report.chunks_embedded += 1

            except Exception as db_exc:
                logger.exception(
                    "Database savepoint failed for batch of %d embeddings: %s",
                    len(chunks_to_embed),
                    db_exc,
                )
                report.chunks_failed += len(chunks_to_embed)
                try:
                    self.db.rollback()
                except Exception:
                    pass

        report.duration_seconds = time.perf_counter() - start_time
        logger.info(
            "Embedding run completed: %d chunks inspected in %.2fs (embedded=%d, updated=%d, skipped=%d, failed=%d, dry_run=%s)",
            report.total_chunks_inspected,
            report.duration_seconds,
            report.chunks_embedded,
            report.chunks_updated,
            report.chunks_skipped,
            report.chunks_failed,
            report.dry_run,
        )
        return report
