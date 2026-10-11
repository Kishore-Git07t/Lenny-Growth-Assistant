"""Alembic environment configuration script.

Working directory:
    Alembic must be invoked from the ``backend/`` directory so that
    ``alembic.ini`` (located at ``backend/alembic.ini``) is found:

        cd E:\\OogwayLabs\\Lenny-Growth-Assistant\\backend
        alembic upgrade head

    The sys.path manipulation below ensures ``backend.app`` is importable
    regardless of the working directory.

DATABASE_URL requirement:
    DATABASE_URL must be explicitly set in the project root ``.env`` file
    (or in the process environment) before running any migration command.
    No implicit fallback URLs are ever used.  A missing DATABASE_URL
    raises a clear RuntimeError with actionable remediation steps.
    Credentials are never printed or logged.
"""

from logging.config import fileConfig
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# sys.path setup
# Compute paths from the absolute location of this file so that imports
# work correctly regardless of the process working directory.
# ---------------------------------------------------------------------------
_current_dir = os.path.abspath(os.path.dirname(__file__))
_backend_dir = os.path.abspath(os.path.join(_current_dir, ".."))    # backend/
_project_root = os.path.abspath(os.path.join(_backend_dir, ".."))   # project root

for _p in (_project_root, _backend_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# These imports must come after sys.path is configured.
from backend.app.config import get_settings, get_project_root          # noqa: E402
from backend.app.database import normalize_database_url                 # noqa: E402
from backend.app.models import Base                                     # noqa: E402

# ---------------------------------------------------------------------------
# Alembic configuration
# ---------------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Database URL resolution
# ---------------------------------------------------------------------------
def get_target_database_url() -> str:
    """Return the validated database URL for Alembic migrations.

    Resolution order:
        1. ``DATABASE_URL`` via pydantic-settings (reads project root .env
           using the absolute path computed in ``config.py``).
        2. ``DATABASE_URL`` from the process environment directly (redundant
           safety layer in case settings caching interferes).

    No hardcoded fallback URL is ever used.  A missing DATABASE_URL raises
    a RuntimeError with step-by-step remediation instructions.

    Credentials are NOT included in any log or error message.

    Raises:
        RuntimeError: If DATABASE_URL is absent from both the .env file and
            the process environment.
    """
    settings = get_settings()
    url = settings.database_url or os.getenv("DATABASE_URL")

    if not url:
        project_root = get_project_root()
        raise RuntimeError(
            "DATABASE_URL is not configured. Alembic cannot run migrations without "
            "an explicit database URL.\n\n"
            "Remediation steps:\n"
            f"  1. Copy .env.example to .env at the project root:\n"
            f"       {project_root}\\.env\n"
            "  2. Open .env and replace POSTGRES_PASSWORD with a real local password.\n"
            "  3. Verify that DATABASE_URL is present and uses the psycopg3 driver:\n"
            "       DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/lenny_assistant\n"
            "  4. Start PostgreSQL: docker compose up -d postgres\n"
            "  5. Re-run Alembic from the backend/ directory:\n"
            "       cd backend\n"
            "       alembic upgrade head"
        )

    return normalize_database_url(url)


# ---------------------------------------------------------------------------
# Migration runners
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Generate migration SQL without a live database connection.

    DATABASE_URL must still be configured so that the correct SQL dialect
    (PostgreSQL / psycopg3) is used when producing the output SQL script.
    """
    url = get_target_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live PostgreSQL connection.

    DATABASE_URL must be configured and PostgreSQL must be reachable.
    Uses NullPool so that the migration connection is released immediately
    after completion rather than being retained in a pool.
    """
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_target_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
