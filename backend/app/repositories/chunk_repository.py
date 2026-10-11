"""Repository functions for TranscriptChunk persistence and queries."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.models.chunk import TranscriptChunk


def create_chunks(
    db: Session, chunks_data: List[Dict[str, Any]], commit: bool = True
) -> List[TranscriptChunk]:
    """Create and persist multiple TranscriptChunk records within the active transaction."""
    now = datetime.now(timezone.utc)
    chunk_instances: List[TranscriptChunk] = []

    for item in chunks_data:
        chunk = TranscriptChunk(
            id=item.get("id") or uuid.uuid4(),
            episode_id=item["episode_id"],
            chunk_index=item["chunk_index"],
            content=item["content"],
            word_count=item.get("word_count") or len(item["content"].split()),
            char_start=item.get("char_start"),
            char_end=item.get("char_end"),
            start_seconds=item.get("start_seconds"),
            end_seconds=item.get("end_seconds"),
            source_checksum=item["source_checksum"],
            config_fingerprint=item.get("config_fingerprint", "v1_default"),
            created_at=now,
            updated_at=now,
        )
        chunk_instances.append(chunk)

    db.add_all(chunk_instances)
    if commit:
        db.commit()
    return chunk_instances


def get_chunks_by_episode_id(db: Session, episode_id: uuid.UUID) -> List[TranscriptChunk]:
    """Retrieve all chunks for an episode ordered sequentially by chunk_index."""
    stmt = (
        select(TranscriptChunk)
        .where(TranscriptChunk.episode_id == episode_id)
        .order_by(TranscriptChunk.chunk_index.asc())
    )
    return list(db.scalars(stmt).all())


def get_chunk_checksum_for_episode(db: Session, episode_id: uuid.UUID) -> Optional[str]:
    """Retrieve the source_checksum of existing chunks for an episode, or None if no chunks exist."""
    stmt = (
        select(TranscriptChunk.source_checksum)
        .where(TranscriptChunk.episode_id == episode_id)
        .limit(1)
    )
    return db.scalar(stmt)


def get_chunk_checksum_and_fingerprint_for_episode(
    db: Session, episode_id: uuid.UUID
) -> Tuple[Optional[str], Optional[str]]:
    """Retrieve the source_checksum and config_fingerprint of existing chunks for an episode."""
    stmt = (
        select(TranscriptChunk.source_checksum, TranscriptChunk.config_fingerprint)
        .where(TranscriptChunk.episode_id == episode_id)
        .limit(1)
    )
    row = db.execute(stmt).first()
    if row:
        return row[0], row[1]
    return None, None


def delete_chunks_by_episode_id(db: Session, episode_id: uuid.UUID, commit: bool = True) -> int:
    """Delete all chunks belonging to an episode and return the count of deleted chunks."""
    stmt = delete(TranscriptChunk).where(TranscriptChunk.episode_id == episode_id)
    result = db.execute(stmt)
    if commit:
        db.commit()
    return result.rowcount or 0


def count_chunks(db: Session) -> int:
    """Count total transcript chunks stored in the database."""
    stmt = select(func.count(TranscriptChunk.id))
    return db.scalar(stmt) or 0


def count_chunks_for_episode(db: Session, episode_id: uuid.UUID) -> int:
    """Count transcript chunks for a specific episode."""
    stmt = select(func.count(TranscriptChunk.id)).where(TranscriptChunk.episode_id == episode_id)
    return db.scalar(stmt) or 0
