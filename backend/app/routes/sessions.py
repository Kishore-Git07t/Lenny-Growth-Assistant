"""API endpoints for managing chat sessions and messages."""

from typing import List
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.repositories import (
    create_message,
    create_session,
    get_session_by_id,
    list_messages_by_session,
    list_sessions,
    update_session,
)
from backend.app.agent import AgentService, get_agent_service, Ship30EssayOrchestrator, HtmlArtifactOrchestrator
from backend.app.schemas import (
    AgentRespondRequest,
    AgentRespondResponse,
    ArtifactGenerateRequest,
    ArtifactResponse,
    ErrorResponse,
    EssayGenerateRequest,
    EssayResponse,
    MessageCreate,
    MessageListResponse,
    MessageResponse,
    SessionCreate,
    SessionListResponse,
    SessionResponse,
    SessionUpdate,
)

_essay_orchestrator_instance = None
_html_orchestrator_instance = None


def get_essay_orchestrator() -> Ship30EssayOrchestrator:
    """Dependency provider for Ship30EssayOrchestrator."""
    global _essay_orchestrator_instance
    if _essay_orchestrator_instance is None:
        _essay_orchestrator_instance = Ship30EssayOrchestrator()
    return _essay_orchestrator_instance


def get_html_artifact_orchestrator() -> HtmlArtifactOrchestrator:
    """Dependency provider for HtmlArtifactOrchestrator."""
    global _html_orchestrator_instance
    if _html_orchestrator_instance is None:
        _html_orchestrator_instance = HtmlArtifactOrchestrator()
    return _html_orchestrator_instance

router = APIRouter(
    prefix="/api/sessions",
    tags=["Sessions"],
    responses={
        503: {"model": ErrorResponse, "description": "Database unavailable"},
    },
)


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new conversation session",
    responses={
        201: {"description": "Session created successfully"},
    },
)
def create_new_session(
    payload: SessionCreate,
    db: Session = Depends(get_db),
) -> SessionResponse:
    """Create an independent chat session with an optional title and user metadata."""
    session = create_session(
        db=db,
        title=payload.title,
        user_metadata=payload.user_metadata,
    )
    return SessionResponse.model_validate(session)


@router.get(
    "",
    response_model=SessionListResponse,
    status_code=status.HTTP_200_OK,
    summary="List saved conversation sessions",
)
def get_sessions(
    limit: int = Query(default=20, ge=1, le=100, description="Page limit (max 100)"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    db: Session = Depends(get_db),
) -> SessionListResponse:
    """Retrieve saved chat sessions, ordered by most recently updated first."""
    items, total = list_sessions(db=db, limit=limit, offset=offset)
    return SessionListResponse(
        items=[SessionResponse.model_validate(s) for s in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get details of a specific session",
    responses={
        404: {"model": ErrorResponse, "description": "Session not found"},
        422: {"description": "Invalid UUID format"},
    },
)
def get_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> SessionResponse:
    """Retrieve details of a single conversation session by its UUID."""
    session = get_session_by_id(db=db, session_id=session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id}' not found.",
        )
    return SessionResponse.model_validate(session)


@router.patch(
    "/{session_id}",
    response_model=SessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Update conversation session details (e.g. title)",
    responses={
        404: {"model": ErrorResponse, "description": "Session not found"},
        422: {"description": "Validation error (e.g. empty title)"},
    },
)
def update_session_details(
    session_id: uuid.UUID,
    payload: SessionUpdate,
    db: Session = Depends(get_db),
) -> SessionResponse:
    """Update title and/or user_metadata for an existing conversation session."""
    session = get_session_by_id(db=db, session_id=session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id}' not found.",
        )

    updated = update_session(
        db=db,
        session_id=session_id,
        title=payload.title,
        user_metadata=payload.user_metadata,
    )
    return SessionResponse.model_validate(updated)



@router.post(
    "/{session_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save a user message in an existing conversation",
    responses={
        201: {"description": "Message saved successfully"},
        404: {"model": ErrorResponse, "description": "Session not found"},
        422: {"description": "Validation error (e.g. empty message)"},
    },
)
def post_message(
    session_id: uuid.UUID,
    payload: MessageCreate,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Save a user message within an existing conversation session.

    The message role is strictly assigned by the backend as 'user' to prevent
    unauthorized impersonation of assistant or system messages.
    """
    session = get_session_by_id(db=db, session_id=session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id}' not found.",
        )

    message = create_message(
        db=db,
        session_id=session_id,
        role="user",
        content=payload.content,
        source_metadata=None,
    )
    return MessageResponse.model_validate(message)


@router.get(
    "/{session_id}/messages",
    response_model=MessageListResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve message history for a session",
    responses={
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
def get_session_messages(
    session_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100, description="Page limit (max 100)"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    db: Session = Depends(get_db),
) -> MessageListResponse:
    """Retrieve messages belonging to a session in chronological order."""
    session = get_session_by_id(db=db, session_id=session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id}' not found.",
        )

    items, total = list_messages_by_session(
        db=db,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    return MessageListResponse(
        items=[MessageResponse.model_validate(m) for m in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{session_id}/respond",
    response_model=AgentRespondResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate an assistant response using Pi Coding Agent and persist conversation turn",
    responses={
        200: {"description": "Assistant response generated and saved successfully"},
        404: {"model": ErrorResponse, "description": "Session not found"},
        502: {"description": "Pi Coding Agent runtime execution failed"},
        503: {"description": "Pi Coding Agent package is not installed or database unavailable"},
        504: {"description": "Pi Coding Agent generation timed out"},
    },
)
async def generate_response_for_session(
    session_id: uuid.UUID,
    payload: AgentRespondRequest,
    db: Session = Depends(get_db),
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentRespondResponse:
    """Generate and persist an assistant response for the conversation session using genuine Pi Coding Agent RPC.

    Saves the user prompt in the session, executes generation through the isolated Pi runtime,
    and persists the completed assistant response in PostgreSQL.
    """
    return await agent_service.generate_session_response(
        db=db,
        session_id=session_id,
        content=payload.content,
        provider=payload.provider,
        model=payload.model,
    )


@router.post(
    "/{session_id}/essay",
    response_model=EssayResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a structured Ship 30 for 30 essay from podcast transcript insights",
    responses={
        201: {"description": "Essay generated and persisted successfully"},
        404: {"model": ErrorResponse, "description": "Session not found"},
        502: {"description": "Pi Coding Agent runtime execution failed"},
        503: {"description": "Embedding or Pi service unavailable"},
        504: {"description": "Essay generation timed out"},
    },
)
async def generate_essay_for_session(
    session_id: uuid.UUID,
    payload: EssayGenerateRequest,
    db: Session = Depends(get_db),
    orchestrator: Ship30EssayOrchestrator = Depends(get_essay_orchestrator),
) -> EssayResponse:
    """Transform grounded Lenny's Podcast insights into a ~1,250-word Ship 30 for 30 digital essay."""
    return await orchestrator.generate_essay(
        session_id=session_id,
        topic=payload.topic,
        audience=payload.audience,
        target_word_count=payload.target_word_count or 1250,
        provider=payload.provider,
        model=payload.model,
        db=db,
    )


@router.get(
    "/{session_id}/essay",
    response_model=EssayResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve the latest generated essay artifact for a conversation session",
    responses={
        404: {"model": ErrorResponse, "description": "Session or essay artifact not found"},
    },
)
def get_latest_essay_for_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> EssayResponse:
    """Retrieve the most recently generated Ship 30 for 30 essay artifact for this session."""
    session = get_session_by_id(db=db, session_id=session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id}' not found.",
        )

    # Search chronological messages in reverse for the latest essay artifact
    messages, _ = list_messages_by_session(db=db, session_id=session_id, limit=100, offset=0)
    for msg in reversed(messages):
        meta = msg.source_metadata or {}
        if meta.get("artifact_type") == "ship30_essay":
            return EssayResponse(
                session_id=session_id,
                message_id=msg.id,
                artifact_type="ship30_essay",
                title=meta.get("title", "Ship 30 for 30 Essay"),
                topic=meta.get("topic", ""),
                audience=meta.get("audience", ""),
                content=msg.content,
                word_count=meta.get("word_count", 0),
                target_word_count=meta.get("target_word_count", 1250),
                status=meta.get("status", "completed"),
                provider=meta.get("provider", "ollama"),
                model=meta.get("model", "qwen2.5:1.5b"),
                citations=meta.get("citations", []),
                coverage=meta.get("coverage"),
                disclaimer=meta.get("disclaimer"),
                created_at=msg.created_at,
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No generated essay artifact found for session '{session_id}'.",
    )


@router.post(
    "/{session_id}/artifact",
    response_model=ArtifactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a professional, sanitized HTML/CSS artifact for a conversation session",
    responses={
        201: {"description": "Artifact generated, sanitized, and persisted successfully"},
        404: {"model": ErrorResponse, "description": "Session not found"},
        502: {"description": "Pi Coding Agent runtime execution failed"},
        504: {"description": "Artifact generation timed out"},
    },
)
async def generate_artifact_for_session(
    session_id: uuid.UUID,
    payload: ArtifactGenerateRequest,
    db: Session = Depends(get_db),
    orchestrator: HtmlArtifactOrchestrator = Depends(get_html_artifact_orchestrator),
) -> ArtifactResponse:
    """Generate, sanitize, and persist a responsive HTML/CSS design artifact using Pi Coding Agent."""
    return await orchestrator.generate_artifact(
        session_id=session_id,
        prompt=payload.prompt,
        title=payload.title,
        artifact_type=payload.artifact_type or "landing_page",
        style_preferences=payload.style_preferences,
        include_podcast_context=payload.include_podcast_context if payload.include_podcast_context is not None else True,
        provider=payload.provider,
        model=payload.model,
        db=db,
    )


@router.get(
    "/{session_id}/artifact",
    response_model=ArtifactResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve the latest saved HTML/CSS artifact for a conversation session",
    responses={
        404: {"model": ErrorResponse, "description": "Session or artifact not found"},
    },
)
def get_latest_artifact_for_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ArtifactResponse:
    """Retrieve the most recently generated HTML/CSS artifact for this session."""
    session = get_session_by_id(db=db, session_id=session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id}' not found.",
        )

    # Search chronological messages in reverse for the latest HTML artifact
    messages, _ = list_messages_by_session(db=db, session_id=session_id, limit=100, offset=0)
    for msg in reversed(messages):
        meta = msg.source_metadata or {}
        if meta.get("artifact_type") == "html_artifact":
            return ArtifactResponse(
                artifact_id=msg.id,
                session_id=session_id,
                title=meta.get("title", "HTML Artifact"),
                artifact_type=meta.get("category", "landing_page"),
                prompt=meta.get("prompt", ""),
                html=meta.get("html", ""),
                css=meta.get("css", ""),
                combined_preview=meta.get("combined_preview", ""),
                status=meta.get("status", "completed"),
                provider=meta.get("provider", "ollama"),
                model=meta.get("model"),
                created_at=msg.created_at,
                diagnostics=meta.get("diagnostics", []),
                citations=meta.get("citations", []),
                coverage=meta.get("coverage"),
                disclaimer=meta.get("disclaimer"),
                is_persisted=True,
            )


    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No generated HTML/CSS artifact found for session '{session_id}'.",
    )

