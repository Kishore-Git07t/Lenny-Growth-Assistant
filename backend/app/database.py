from contextlib import contextmanager
import logging
from typing import Generator, Optional, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


class DatabaseUnconfiguredException(Exception):
    """Raised when an operation requires a database, but DATABASE_URL is not set."""
    pass


class DatabaseUnavailableException(Exception):
    """Raised when an operation fails due to database connectivity errors."""
    pass


_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker[Session]] = None


def normalize_database_url(raw_url: str) -> str:
    """Ensure PostgreSQL URL uses the psycopg (v3) driver if standard postgresql:// is provided."""
    if raw_url.startswith("postgresql://") and not raw_url.startswith("postgresql+psycopg://"):
        return raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql+psycopg://", 1)
    return raw_url


def get_engine() -> Optional[Engine]:
    """Return the global SQLAlchemy Engine, initializing lazily if configured."""
    global _engine, _session_factory
    settings = get_settings()

    if not settings.database_url:
        return None

    if _engine is None:
        db_url = normalize_database_url(settings.database_url)
        # Configure connection arguments and pool parameters
        is_sqlite = db_url.startswith("sqlite")
        engine_kwargs = {
            "pool_pre_ping": True,
        }
        if not is_sqlite:
            engine_kwargs.update({
                "pool_size": settings.db_pool_size,
                "max_overflow": settings.db_max_overflow,
                "pool_timeout": settings.db_pool_timeout,
            })

        _engine = create_engine(db_url, **engine_kwargs)
        _session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=_engine,
            expire_on_commit=False,
        )

    return _engine


def get_session_factory() -> Optional[sessionmaker[Session]]:
    """Return the active session factory if engine is initialized."""
    get_engine()
    return _session_factory


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager yielding a managed database session for scripts, CLI, and standalone tasks.

    Handles connection verification on checkout, rollback on database errors,
    and guaranteed session closure upon context exit.

    Raises:
        DatabaseUnconfiguredException: If DATABASE_URL is not configured.
        DatabaseUnavailableException: If unable to acquire a connection to the database.
    """
    factory = get_session_factory()
    if factory is None:
        raise DatabaseUnconfiguredException("Database is not configured. Set DATABASE_URL in environment.")

    db: Optional[Session] = None
    try:
        db = factory()
        # Verify connection on checkout
        db.execute(text("SELECT 1"))
        yield db
    except OperationalError as exc:
        logger.error("Database connection failure during session acquisition: %s", exc)
        raise DatabaseUnavailableException(f"Database service is unavailable: {exc}") from exc
    except SQLAlchemyError as exc:
        logger.error("Database error during session: %s", exc)
        if db:
            db.rollback()
        raise
    finally:
        if db:
            db.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding an isolated database session.

    Raises:
        DatabaseUnconfiguredException: If DATABASE_URL is not configured.
        DatabaseUnavailableException: If unable to acquire a connection to the database.
    """
    with get_db_session() as session:
        yield session


def check_db_connectivity() -> Tuple[bool, str]:
    """Check current database connectivity status without raising unhandled exceptions.

    Returns:
        (is_connected, status_code_or_reason):
            (True, "connected") if database is healthy
            (False, "unconfigured") if DATABASE_URL is unset
            (False, "unavailable: <reason>") if connection failed
    """
    settings = get_settings()
    if not settings.database_url:
        return False, "unconfigured"

    try:
        engine = get_engine()
        if engine is None:
            return False, "unconfigured"

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "connected"
    except Exception as exc:
        logger.warning("Database connectivity check failed: %s", exc)
        return False, f"unavailable: {str(exc)}"


def reset_engine_for_testing() -> None:
    """Reset cached engine and sessionmaker (used by test suites)."""
    global _engine, _session_factory
    if _engine:
        _engine.dispose()
    _engine = None
    _session_factory = None
