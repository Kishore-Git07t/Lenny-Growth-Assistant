"""SQLAlchemy model for Lenny's Podcast episodes and transcripts."""

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import Date, DateTime, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from backend.app.database import Base


class PodcastEpisode(Base):
    """Database model representing an ingested Lenny's Podcast episode transcript."""

    __tablename__ = "podcast_episodes"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    guest_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    publish_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        index=True,
    )
    youtube_url: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True,
    )
    video_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    source_path: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True,
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    transcript_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    content_checksum: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    raw_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
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

    __table_args__ = (
        Index("idx_podcast_episodes_created_at", "created_at"),
        Index("idx_podcast_episodes_guest_name", "guest_name"),
        Index("idx_podcast_episodes_checksum", "content_checksum"),
    )
