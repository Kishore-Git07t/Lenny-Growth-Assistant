"""FastAPI Backend Application for Lenny Growth Assistant.

Phase 2, Step 2.1: PostgreSQL persistence foundation, conversation session
and message APIs, and readiness health probes.
"""

from datetime import datetime, timezone
import logging
from typing import Dict, Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.app.config import get_settings
from backend.app.database import (
    DatabaseUnavailableException,
    DatabaseUnconfiguredException,
    check_db_connectivity,
)
from backend.app.routes import models_router, ready_router, sessions_router

logger = logging.getLogger(__name__)

settings = get_settings()

# Configure application logging to ensure backend logs emit to console
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("backend").setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

APP_NAME = "Lenny Growth Assistant Backend"
APP_VERSION = "0.2.0"

class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


app = FastAPI(
    default_response_class=UTF8JSONResponse,
    title=APP_NAME,
    version=APP_VERSION,
    description=(
        "Backend API service for Lenny Growth Assistant - an AI-powered conversational "
        "knowledge assistant transforming Lenny's Podcast transcripts into actionable insights."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)


# CORS Middleware Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception Handlers for Database Errors
@app.exception_handler(DatabaseUnconfiguredException)
def handle_db_unconfigured(request: Request, exc: DatabaseUnconfiguredException) -> JSONResponse:
    """Handle unconfigured database error with structured HTTP 503 response."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": "database_unconfigured",
            "message": "Database is not configured. Set DATABASE_URL in environment.",
            "status_code": 503,
        },
    )


@app.exception_handler(DatabaseUnavailableException)
def handle_db_unavailable(request: Request, exc: DatabaseUnavailableException) -> JSONResponse:
    """Handle database connection error with structured HTTP 503 response."""
    logger.error("Database connection failure at endpoint %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": "database_unavailable",
            "message": "Database service is currently unavailable. Please check database connectivity.",
            "status_code": 503,
        },
    )


# Mount Routers
app.include_router(ready_router)
app.include_router(sessions_router)
app.include_router(models_router)



class HealthResponse(BaseModel):
    """Structured health check response model."""

    status: str = Field(..., description="Overall health status", example="ok")
    service: str = Field(..., description="Name of the backend service", example="lenny-growth-assistant-backend")
    version: str = Field(..., description="Application version", example="0.2.0")
    timestamp: str = Field(..., description="UTC ISO 8601 timestamp", example="2026-10-09T12:00:00Z")
    environment: str = Field(..., description="Current running environment", example="development")
    llm_provider: str = Field(..., description="Currently active LLM provider", example="ollama")
    model: str = Field(..., description="Configured active model", example="qwen2.5:1.5b")
    components: Dict[str, str] = Field(
        default_factory=dict,
        description="Subsystem operational states (database, retrieval, agent)",
    )


@app.get("/api/health", response_model=HealthResponse, tags=["Health"])
def get_health() -> HealthResponse:
    """Return structured health status of the backend service.

    Preserves the liveness contract: does not fail even if database is unconfigured.
    """
    is_db_connected, db_reason = check_db_connectivity()
    if is_db_connected:
        db_component_status = "operational"
    elif db_reason == "unconfigured":
        db_component_status = "not configured (pending Phase 2)"
    else:
        db_component_status = f"unavailable: {db_reason}"

    return HealthResponse(
        status="ok",
        service="lenny-growth-assistant-backend",
        version=APP_VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
        environment=settings.environment,
        llm_provider=settings.llm_provider,
        model=settings.ollama_model,
        components={
            "api": "operational",
            "database": db_component_status,
            "retrieval": "not configured (pending Phase 2)",
            "ollama": "not checked",
            "agent_runtime": "not configured (pending Phase 3)",
        },
    )


@app.get("/", tags=["Root"])
def get_root() -> Dict[str, Any]:
    """Root endpoint providing service information and links."""
    return {
        "service": APP_NAME,
        "version": APP_VERSION,
        "status": "online",
        "docs": "/docs",
        "health": "/api/health",
        "ready": "/api/ready",
    }
