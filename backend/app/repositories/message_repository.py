"""Repository functions for ChatMessage persistence and queries."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.message import ChatMessage
from backend.app.repositories.session_repository import touch_session


def create_message(
    db: Session,
    session_id: uuid.UUID,
    role: str,
    content: str,
    source_metadata: Optional[Dict[str, Any]] = None,
) -> ChatMessage:
    """Create and persist a new ChatMessage and update the parent session timestamp."""
    now = datetime.now(timezone.utc)
    message = ChatMessage(
        id=uuid.uuid4(),
        session_id=session_id,
        role=role,
        content=content,
        source_metadata=source_metadata,
        created_at=now,
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    # Touch parent session updated_at
    touch_session(db, session_id)

    return message


def list_messages_by_session(
    db: Session,
    session_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[ChatMessage], int]:
    """Retrieve paginated messages for a session in chronological order with a stable tie-breaker."""
    count_stmt = select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
    total = db.scalar(count_stmt) or 0

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.scalars(stmt).all())
    return items, total
