"""Repository functions for PodcastEpisode persistence and queries."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.episode import PodcastEpisode
from backend.app.utils.serialization import make_json_serializable


def create_episode(db: Session, episode_data: Dict[str, Any]) -> PodcastEpisode:
    """Create and persist a new PodcastEpisode."""
    now = datetime.now(timezone.utc)
    raw_meta = make_json_serializable(episode_data.get("raw_metadata") or {})
    episode = PodcastEpisode(
        id=episode_data.get("id") or uuid.uuid4(),
        slug=episode_data["slug"],
        guest_name=episode_data.get("guest_name"),
        title=episode_data["title"],
        publish_date=episode_data.get("publish_date"),
        youtube_url=episode_data.get("youtube_url"),
        video_id=episode_data.get("video_id"),
        source_path=episode_data.get("source_path"),
        description=episode_data.get("description"),
        transcript_text=episode_data["transcript_text"],
        content_checksum=episode_data["content_checksum"],
        raw_metadata=raw_meta,
        created_at=now,
        updated_at=now,
    )
    db.add(episode)
    db.commit()
    db.refresh(episode)
    return episode


def get_episode_by_id(db: Session, episode_id: uuid.UUID) -> Optional[PodcastEpisode]:
    """Retrieve an episode by primary key UUID."""
    stmt = select(PodcastEpisode).where(PodcastEpisode.id == episode_id)
    return db.scalars(stmt).first()


def get_episode_by_slug(db: Session, slug: str) -> Optional[PodcastEpisode]:
    """Retrieve an episode by its unique slug."""
    stmt = select(PodcastEpisode).where(PodcastEpisode.slug == slug)
    return db.scalars(stmt).first()


def update_episode(
    db: Session,
    episode: PodcastEpisode,
    update_data: Dict[str, Any],
) -> PodcastEpisode:
    """Update an existing episode's fields and set updated_at to UTC now."""
    for field, val in update_data.items():
        if hasattr(episode, field) and field not in ("id", "created_at"):
            if field == "raw_metadata":
                val = make_json_serializable(val or {})
            setattr(episode, field, val)

    episode.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(episode)
    return episode


def list_episodes(
    db: Session,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[PodcastEpisode], int]:
    """Retrieve paginated episodes ordered by publish_date descending, along with total count."""
    count_stmt = select(func.count(PodcastEpisode.id))
    total = db.scalar(count_stmt) or 0

    stmt = (
        select(PodcastEpisode)
        .order_by(PodcastEpisode.publish_date.desc().nullslast(), PodcastEpisode.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.scalars(stmt).all())
    return items, total


def count_episodes(db: Session) -> int:
    """Count total ingested podcast episodes."""
    stmt = select(func.count(PodcastEpisode.id))
    return db.scalar(stmt) or 0
