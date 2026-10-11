"""Application configuration management using Pydantic Settings.

Environment file resolution:
    The root .env file is located at the project root:
        E:\\OogwayLabs\\Lenny-Growth-Assistant\\.env

    The path is derived at import time using the absolute location of this
    source file (backend/app/config.py), traversing two directories up to
    reach the project root.  This makes the resolution independent of the
    process working directory, so the same .env is found whether:
      - FastAPI is launched from the project root
          uvicorn backend.app.main:app ...
      - Alembic is launched from backend/
          cd backend && alembic upgrade head
      - pytest is launched from the project root
          pytest backend/tests/ -v

    Environment variables present in the process environment always take
    precedence over values in .env (standard pydantic-settings behaviour).
"""

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the project root as two levels above this file:
#   backend/app/config.py  ->  backend/app/  ->  backend/  ->  project root
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_ENV_FILE: Path = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables and the root .env file.

    Precedence (highest to lowest):
        1. Real process environment variables (e.g. set in the shell or CI).
        2. Variables in the root .env file at ``E:\\OogwayLabs\\Lenny-Growth-Assistant\\.env``.
        3. Field ``default`` values defined below.

    DATABASE_URL is intentionally optional (default None) so that FastAPI
    can start and serve health/liveness endpoints without a live database.
    Alembic enforces its own explicit check and raises a RuntimeError when
    DATABASE_URL is absent.
    """

    # Application Environment
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    # CORS Configuration
    backend_cors_origins: List[str] = Field(
        default=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ],
        alias="BACKEND_CORS_ORIGINS",
    )

    # Database Configuration (PostgreSQL & Docker)
    # Individual PostgreSQL variables are consumed by Docker Compose via .env.
    # The application itself uses only DATABASE_URL for connectivity.
    postgres_user: Optional[str] = Field(default="postgres", alias="POSTGRES_USER")
    postgres_password: Optional[str] = Field(default=None, alias="POSTGRES_PASSWORD")
    postgres_db: Optional[str] = Field(default="lenny_assistant", alias="POSTGRES_DB")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")

    # DATABASE_URL — optional for FastAPI startup; required for Alembic migrations.
    # Must use the psycopg3 driver prefix: postgresql+psycopg://
    database_url: Optional[str] = Field(default=None, alias="DATABASE_URL")
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")

    # LLM Provider Configuration
    llm_provider: str = Field(default="ollama", alias="LLM_PROVIDER")
    ollama_model: str = Field(default="qwen2.5:1.5b", alias="OLLAMA_MODEL")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_timeout_seconds: int = Field(default=60, alias="OLLAMA_TIMEOUT_SECONDS")

    # Embedding Pipeline Configuration (Phase 3.2B-2)
    embedding_model: str = Field(default="nomic-embed-text", alias="EMBEDDING_MODEL")
    embedding_dimensions: int = Field(default=768, alias="EMBEDDING_DIMENSIONS")
    embedding_batch_size: int = Field(default=4, alias="EMBEDDING_BATCH_SIZE")
    embedding_timeout_seconds: int = Field(default=60, alias="EMBEDDING_TIMEOUT_SECONDS")
    embedding_max_retries: int = Field(default=3, alias="EMBEDDING_MAX_RETRIES")

    # Cloud LLM Provider: Google Gemini API (Free tier available via Google AI Studio)
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")

    # Optional legacy cloud LLMs (retained for backward compatibility)
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-3-5-sonnet-20241022", alias="ANTHROPIC_MODEL")

    # Agent Framework Configuration (Pi Coding Agent RPC)
    agent_framework: str = Field(default="pi_agent", alias="AGENT_FRAMEWORK")
    pi_agent_dir: Optional[str] = Field(default=None, alias="PI_CODING_AGENT_DIR")
    pi_agent_timeout_seconds: int = Field(default=120, alias="PI_AGENT_TIMEOUT_SECONDS")
    pi_agent_runtime_path: Optional[str] = Field(default=None, alias="PI_AGENT_RUNTIME_PATH")
    pi_agent_executable: Optional[str] = Field(default=None, alias="PI_AGENT_EXECUTABLE")
    pi_agent_host: str = Field(default="localhost", alias="PI_AGENT_HOST")
    pi_agent_port: int = Field(default=9000, alias="PI_AGENT_PORT")

    # Authentic Pi Evidence Capture (Opt-in, disabled by default)
    pi_capture_events: bool = Field(default=False, alias="PI_CAPTURE_EVENTS")
    pi_evidence_dir: str = Field(default=".local/pi-evidence", alias="PI_EVIDENCE_DIR")

    # Ship 30 for 30 Essay Skill Configuration
    essay_outline_timeout_seconds: int = Field(
        default=180,
        alias="ESSAY_OUTLINE_TIMEOUT_SECONDS",
    )
    essay_section_timeout_seconds: int = Field(
        default=180,
        alias="ESSAY_SECTION_TIMEOUT_SECONDS",
    )
    essay_total_timeout_seconds: int = Field(
        default=900,
        alias="ESSAY_TOTAL_TIMEOUT_SECONDS",
    )

    # Transcript Corpus Ingestion Configuration (Phase 3 Step 3.2A)
    corpus_transcripts_dir: str = Field(
        default=".local/corpus/lennys-podcast-transcripts",
        alias="CORPUS_TRANSCRIPTS_DIR",
    )

    # Grounded RAG Configuration (Phase 3.2C-2)
    rag_top_k: int = Field(default=5, alias="RAG_TOP_K")
    rag_max_passages_in_prompt: int = Field(default=3, alias="RAG_MAX_PASSAGES_IN_PROMPT")
    rag_max_chars_per_passage: int = Field(default=600, alias="RAG_MAX_CHARS_PER_PASSAGE")
    rag_max_total_evidence_chars: int = Field(default=1800, alias="RAG_MAX_TOTAL_EVIDENCE_CHARS")

    model_config = SettingsConfigDict(
        # Absolute path ensures .env is found regardless of process working directory.
        # env_ignore_empty=True means empty string values in .env are treated as unset,
        # preventing an empty DATABASE_URL= line from shadowing a real env var.
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return a cached instance of application settings.

    The cache is module-level and persists for the lifetime of the process.
    To reload settings (e.g. in tests), call ``get_settings.cache_clear()``
    before invoking ``get_settings()`` again.
    """
    return Settings()


def get_project_root() -> Path:
    """Return the absolute path to the project root directory.

    Useful for other modules that need to locate project-relative files
    (e.g. the integration test suite resolving the root .env path).
    """
    return _PROJECT_ROOT
