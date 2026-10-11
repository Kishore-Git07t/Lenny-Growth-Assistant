"""Repository functions for ChatSession persistence and queries."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.session import ChatSession


def create_session(
    db: Session,
    title: Optional[str] = None,
    user_metadata: Optional[Dict[str, Any]] = None,
) -> ChatSession:
    """Create and persist a new ChatSession."""
    now = datetime.now(timezone.utc)
    session = ChatSession(
        id=uuid.uuid4(),
        title=title,
        user_metadata=user_metadata or {},
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session_by_id(db: Session, session_id: uuid.UUID) -> Optional[ChatSession]:
    """Retrieve a ChatSession by its unique UUID."""
    stmt = select(ChatSession).where(ChatSession.id == session_id)
    return db.scalars(stmt).first()


def list_sessions(
    db: Session,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[ChatSession], int]:
    """Retrieve paginated sessions ordered by updated_at descending, along with total count."""
    count_stmt = select(func.count(ChatSession.id))
    total = db.scalar(count_stmt) or 0

    stmt = (
        select(ChatSession)
        .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.scalars(stmt).all())
    return items, total


def touch_session(db: Session, session_id: uuid.UUID) -> Optional[ChatSession]:
    """Update the updated_at timestamp of an existing session to current UTC."""
    session = get_session_by_id(db, session_id)
    if session:
        session.updated_at = datetime.now(timezone.utc)
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def update_session(
    db: Session,
    session_id: uuid.UUID,
    title: Optional[str] = None,
    user_metadata: Optional[Dict[str, Any]] = None,
) -> Optional[ChatSession]:
    """Update title and/or user_metadata of an existing ChatSession."""
    session = get_session_by_id(db, session_id)
    if not session:
        return None

    if title is not None:
        session.title = title
    if user_metadata is not None:
        session.user_metadata = user_metadata

    session.updated_at = datetime.now(timezone.utc)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session

