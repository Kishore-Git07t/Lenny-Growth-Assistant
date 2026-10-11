"""SQLAlchemy model for podcast transcript vector embeddings."""

from datetime import datetime, timezone
import json
from typing import Any, List, Optional
import uuid

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from backend.app.database import Base

# Safe import for pgvector: fallback to a stub type if pgvector is not yet installed
try:
    from pgvector.sqlalchemy import Vector as _PgVector
except ImportError:
    from sqlalchemy.types import UserDefinedType

    class _PgVector(UserDefinedType):  # type: ignore
        """Fallback Vector type when pgvector package is not yet installed."""

        def __init__(self, dim: int = 768):
            self.dim = dim

        def get_col_spec(self, **kw: Any) -> str:
            return f"vector({self.dim})" if self.dim else "vector"


class Vector768(TypeDecorator):
    """Platform-independent 768-dimensional Vector type.

    In PostgreSQL: delegates to native pgvector Vector(768).
    In SQLite (unit testing): serializes list[float] to and from JSON text.
    """

    impl = _PgVector(768)
    cache_ok = True

    class Comparator(TypeDecorator.Comparator):
        """Custom comparator supporting native pgvector distance operators."""

        def cosine_distance(self, other: Any) -> Any:
            return self.op("<=>", return_type=Float)(other)

        def l2_distance(self, other: Any) -> Any:
            return self.op("<->", return_type=Float)(other)

        def max_inner_product(self, other: Any) -> Any:
            return self.op("<#>", return_type=Float)(other)

    comparator_factory = Comparator

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PgVector(768))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        # SQLite storage: serialize list of floats to JSON string
        if isinstance(value, (list, tuple)):
            return json.dumps([float(v) for v in value])
        return str(value)

    def process_result_value(self, value: Any, dialect: Any) -> Optional[List[float]]:
        if value is None:
            return None
        if dialect.name == "postgresql":
            if isinstance(value, str):
                return json.loads(value)
            return list(value)
        # SQLite deserialization: parse JSON string back into list of floats
        if isinstance(value, str):
            return [float(x) for x in json.loads(value)]
        return list(value)


class TranscriptEmbedding(Base):
    """Database model representing a 768-dimensional vector embedding for a transcript chunk."""

    __tablename__ = "transcript_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("transcript_chunks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    embedding: Mapped[List[float]] = mapped_column(
        Vector768,
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    input_checksum: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Bidirectional relationship to parent chunk
    chunk = relationship(
        "TranscriptChunk",
        back_populates="embedding",
    )

    __table_args__ = (
        UniqueConstraint("chunk_id", name="uq_transcript_embeddings_chunk_id"),
        Index("idx_transcript_embeddings_chunk_id", "chunk_id"),
        Index("idx_transcript_embeddings_model_name", "model_name"),
        Index("idx_transcript_embeddings_input_checksum", "input_checksum"),
        Index("idx_transcript_embeddings_created_at", "created_at"),
    )
