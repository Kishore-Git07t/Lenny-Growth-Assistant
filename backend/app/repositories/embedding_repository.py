"""Repository functions for TranscriptEmbedding persistence and queries."""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.models.chunk import TranscriptChunk
from backend.app.models.embedding import TranscriptEmbedding
from backend.app.models.episode import PodcastEpisode


def get_embedding_by_chunk_id(
    db: Session,
    chunk_id: uuid.UUID,
) -> Optional[TranscriptEmbedding]:
    """Retrieve an embedding record by chunk primary key UUID."""
    stmt = select(TranscriptEmbedding).where(TranscriptEmbedding.chunk_id == chunk_id)
    return db.scalars(stmt).first()


def get_embedding_metadata_by_chunk_id(
    db: Session,
    chunk_id: uuid.UUID,
) -> Tuple[Optional[str], Optional[str]]:
    """Retrieve (model_name, input_checksum) for a chunk without loading the vector payload."""
    stmt = (
        select(TranscriptEmbedding.model_name, TranscriptEmbedding.input_checksum)
        .where(TranscriptEmbedding.chunk_id == chunk_id)
        .limit(1)
    )
    row = db.execute(stmt).first()
    if row:
        return row[0], row[1]
    return None, None


def get_existing_embeddings_metadata_for_chunk_ids(
    db: Session,
    chunk_ids: List[uuid.UUID],
) -> Dict[uuid.UUID, Tuple[str, str]]:
    """Batch retrieve {chunk_id: (model_name, input_checksum)} for a list of chunk IDs."""
    if not chunk_ids:
        return {}
    stmt = (
        select(
            TranscriptEmbedding.chunk_id,
            TranscriptEmbedding.model_name,
            TranscriptEmbedding.input_checksum,
        )
        .where(TranscriptEmbedding.chunk_id.in_(chunk_ids))
    )
    rows = db.execute(stmt).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def create_or_update_embedding(
    db: Session,
    chunk_id: uuid.UUID,
    embedding: List[float],
    model_name: str,
    input_checksum: str,
    commit: bool = True,
) -> TranscriptEmbedding:
    """Create or update an embedding for a chunk idempotently."""
    now = datetime.now(timezone.utc)
    existing = get_embedding_by_chunk_id(db, chunk_id)

    if existing:
        existing.embedding = embedding
        existing.model_name = model_name
        existing.input_checksum = input_checksum
        existing.updated_at = now
        record = existing
    else:
        record = TranscriptEmbedding(
            id=uuid.uuid4(),
            chunk_id=chunk_id,
            embedding=embedding,
            model_name=model_name,
            input_checksum=input_checksum,
            created_at=now,
            updated_at=now,
        )
        db.add(record)

    if commit:
        db.commit()
        db.refresh(record)
    return record


def create_or_update_embeddings_batch(
    db: Session,
    items: List[Dict[str, Any]],
    commit: bool = True,
) -> List[TranscriptEmbedding]:
    """Persist multiple embeddings in a batch upsert within the active transaction."""
    if not items:
        return []

    now = datetime.now(timezone.utc)
    chunk_ids = [item["chunk_id"] for item in items]

    # Preload existing embeddings for these chunk IDs
    stmt = select(TranscriptEmbedding).where(TranscriptEmbedding.chunk_id.in_(chunk_ids))
    existing_map = {emb.chunk_id: emb for emb in db.scalars(stmt).all()}

    saved_records: List[TranscriptEmbedding] = []

    for item in items:
        cid = item["chunk_id"]
        vector = item["embedding"]
        mname = item["model_name"]
        ichecksum = item["input_checksum"]

        if cid in existing_map:
            rec = existing_map[cid]
            rec.embedding = vector
            rec.model_name = mname
            rec.input_checksum = ichecksum
            rec.updated_at = now
        else:
            rec = TranscriptEmbedding(
                id=item.get("id") or uuid.uuid4(),
                chunk_id=cid,
                embedding=vector,
                model_name=mname,
                input_checksum=ichecksum,
                created_at=now,
                updated_at=now,
            )
            db.add(rec)
        saved_records.append(rec)

    if commit:
        db.commit()
    return saved_records


def count_embeddings(
    db: Session,
    model_name: Optional[str] = None,
) -> int:
    """Count total stored embeddings, optionally filtered by model_name."""
    stmt = select(func.count(TranscriptEmbedding.id))
    if model_name:
        stmt = stmt.where(TranscriptEmbedding.model_name == model_name)
    return db.scalar(stmt) or 0


def delete_embeddings_by_chunk_id(
    db: Session,
    chunk_id: uuid.UUID,
    commit: bool = True,
) -> int:
    """Delete embedding for a specific chunk."""
    stmt = delete(TranscriptEmbedding).where(TranscriptEmbedding.chunk_id == chunk_id)
    result = db.execute(stmt)
    if commit:
        db.commit()
    return result.rowcount or 0


def semantic_search(
    db: Session,
    query_vector: List[float],
    top_k: int = 5,
    model_name: str = "nomic-embed-text",
) -> List[Tuple[TranscriptChunk, PodcastEpisode, float]]:
    """Perform nearest-neighbor vector similarity search using cosine distance.

    In PostgreSQL: executes native pgvector '<=>' cosine distance query with joins.
    In SQLite (offline testing): computes cosine distance in Python.

    Args:
        db: Active SQLAlchemy session.
        query_vector: 768-D query embedding.
        top_k: Number of nearest matches to retrieve (bounded between 1 and 10).
        model_name: Model identifier to filter matching embeddings.

    Returns:
        List of (TranscriptChunk, PodcastEpisode, cosine_distance) sorted ascending by distance.
    """
    bounded_top_k = max(1, min(10, top_k))

    bind = db.get_bind()
    dialect_name = bind.dialect.name if bind else "postgresql"

    if dialect_name == "postgresql":
        distance_col = TranscriptEmbedding.embedding.cosine_distance(query_vector).label("distance")
        stmt = (
            select(TranscriptChunk, PodcastEpisode, distance_col)
            .join(TranscriptChunk, TranscriptEmbedding.chunk_id == TranscriptChunk.id)
            .join(PodcastEpisode, TranscriptChunk.episode_id == PodcastEpisode.id)
            .where(TranscriptEmbedding.model_name == model_name)
            .order_by(
                distance_col.asc(),
                TranscriptChunk.id.asc(),
            )
            .limit(bounded_top_k)
        )
        rows = db.execute(stmt).all()
        return [(r[0], r[1], float(r[2])) for r in rows]
    else:
        # SQLite offline test compatibility path
        stmt = (
            select(TranscriptEmbedding, TranscriptChunk, PodcastEpisode)
            .join(TranscriptChunk, TranscriptEmbedding.chunk_id == TranscriptChunk.id)
            .join(PodcastEpisode, TranscriptChunk.episode_id == PodcastEpisode.id)
            .where(TranscriptEmbedding.model_name == model_name)
        )
        candidates = db.execute(stmt).all()
        scored: List[Tuple[TranscriptChunk, PodcastEpisode, float]] = []

        norm_q = math.sqrt(sum(x * x for x in query_vector))

        for emb, chunk, ep in candidates:
            vec = emb.embedding
            if isinstance(vec, str):
                import json
                vec = json.loads(vec)
            dot = sum(a * b for a, b in zip(query_vector, vec))
            norm_v = math.sqrt(sum(b * b for b in vec))
            if norm_q == 0.0 or norm_v == 0.0:
                dist = 1.0
            else:
                sim = dot / (norm_q * norm_v)
                dist = max(0.0, min(2.0, 1.0 - sim))
            scored.append((chunk, ep, dist))

        scored.sort(key=lambda item: (item[2], str(item[0].id)))
        return scored[:bounded_top_k]


def get_index_coverage(
    db: Session,
    model_name: str = "nomic-embed-text",
) -> Dict[str, Any]:
    """Retrieve corpus vs indexed counts to honestly report partial index status."""
    total_episodes_stmt = select(func.count(PodcastEpisode.id))
    total_episodes = db.scalar(total_episodes_stmt) or 0

    total_chunks_stmt = select(func.count(TranscriptChunk.id))
    total_chunks = db.scalar(total_chunks_stmt) or 0

    indexed_chunks_stmt = (
        select(func.count(TranscriptEmbedding.id))
        .where(TranscriptEmbedding.model_name == model_name)
    )
    indexed_chunks = db.scalar(indexed_chunks_stmt) or 0

    indexed_episodes_stmt = (
        select(func.count(func.distinct(TranscriptChunk.episode_id)))
        .join(TranscriptEmbedding, TranscriptChunk.id == TranscriptEmbedding.chunk_id)
        .where(TranscriptEmbedding.model_name == model_name)
    )
    indexed_episodes = db.scalar(indexed_episodes_stmt) or 0

    is_partial = (indexed_episodes < total_episodes) or (indexed_chunks < total_chunks)

    return {
        "total_episodes": total_episodes,
        "indexed_episodes": indexed_episodes,
        "total_chunks": total_chunks,
        "indexed_chunks": indexed_chunks,
        "model_name": model_name,
        "is_partial": is_partial,
    }
