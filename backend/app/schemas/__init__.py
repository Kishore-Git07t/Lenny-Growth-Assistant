"""Pydantic schemas package."""

from backend.app.schemas.common import ErrorResponse, PaginationParams
from backend.app.schemas.session import SessionCreate, SessionResponse, SessionListResponse, SessionUpdate
from backend.app.schemas.message import MessageCreate, MessageResponse, MessageListResponse
from backend.app.schemas.agent import AgentRespondRequest, AgentRespondResponse
from backend.app.schemas.essay import (
    EssayGenerateRequest,
    EssayOutline,
    EssayResponse,
    EssaySectionPlan,
)
from backend.app.schemas.artifact import (
    ArtifactGenerateRequest,
    ArtifactResponse,
)

__all__ = [
    "ErrorResponse",
    "PaginationParams",
    "SessionCreate",
    "SessionResponse",
    "SessionListResponse",
    "SessionUpdate",
    "MessageCreate",
    "MessageResponse",
    "MessageListResponse",
    "AgentRespondRequest",
    "AgentRespondResponse",
    "EssayGenerateRequest",
    "EssayOutline",
    "EssayResponse",
    "EssaySectionPlan",
    "ArtifactGenerateRequest",
    "ArtifactResponse",
]
