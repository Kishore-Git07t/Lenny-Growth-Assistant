"""SQLAlchemy model for podcast transcript chunks."""

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class TranscriptChunk(Base):
    """Database model representing a segmented text chunk from a podcast episode transcript."""

    __tablename__ = "transcript_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    episode_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("podcast_episodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    word_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    char_start: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    char_end: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    start_seconds: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        index=True,
    )
    end_seconds: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    source_checksum: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    config_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="v1_default",
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

    # Relationship to parent episode
    episode = relationship(
        "PodcastEpisode",
        backref="chunks",
    )

    # One-to-one relationship to embedding
    embedding = relationship(
        "TranscriptEmbedding",
        back_populates="chunk",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("episode_id", "chunk_index", name="uq_transcript_chunks_episode_index"),
        Index("idx_transcript_chunks_episode_id", "episode_id"),
        Index("idx_transcript_chunks_checksum", "source_checksum"),
        Index("idx_transcript_chunks_config_fingerprint", "config_fingerprint"),
        Index("idx_transcript_chunks_start_seconds", "start_seconds"),
        Index("idx_transcript_chunks_created_at", "created_at"),
    )
