"""Integration test suite against a real PostgreSQL 17 + pgvector database instance.

Prerequisites
-------------
These tests require:
    1. PostgreSQL running via Docker Compose:
           docker compose up -d postgres
    2. The integration test database to exist:
           docker exec -it lenny_postgres psql -U postgres -c "CREATE DATABASE lenny_assistant_test;"
    3. The root .env file to define TEST_POSTGRES_URL pointing at lenny_assistant_test:
           TEST_POSTGRES_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/lenny_assistant_test

Skip behaviour
--------------
The entire class is skipped automatically when TEST_POSTGRES_URL is not set.
This keeps the offline unit-test suite (25 tests) clean and fast.

Schema strategy
---------------
The pg_engine fixture calls ``Base.metadata.create_all()`` to create tables
directly on the test database using the ORM model definitions.  This is
intentional: integration tests are self-contained and do not depend on Alembic
migrations having been applied to the test database.  The development database
(lenny_assistant) is the migration target; the test database (lenny_assistant_test)
is managed exclusively by the test fixtures.

Safety design
-------------
Two independent guards prevent the integration tests from targeting the
development database:
    Guard 1 — Destination equality: the normalised test URL must differ from
        the normalised development URL.
    Guard 2 — Database name: the database name extracted from TEST_POSTGRES_URL
        must contain the word 'test' (case-insensitive).
Both guards run before any DDL or DML is executed.

Credential hygiene
------------------
No credentials appear in test output, assertion messages, or pytest reports.
URLs are referenced only for structural validation (host:port/dbname extraction).
"""

import os
import uuid
import pytest
from urllib.parse import urlparse
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from backend.app.models.session import ChatSession
from backend.app.models.message import ChatMessage

# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------
# TEST_POSTGRES_URL and DATABASE_URL are read exclusively from the environment.
# The root .env is loaded via config.py / pydantic-settings when the application
# boots; pytest does not reload it automatically, so we read from os.getenv
# here to pick up whatever the shell / .env-loading mechanism has exported.
#
# No hardcoded fallback URLs are used. An absent DATABASE_URL defaults to an
# empty string so that Safety Guard 1 (equality check) is never bypassed by
# a matching hardcoded value.
TEST_POSTGRES_URL: str = os.getenv("TEST_POSTGRES_URL", "")
DEV_DATABASE_URL: str = os.getenv("DATABASE_URL", "")


def _extract_db_destination(url: str) -> str:
    """Extract 'host:port/dbname' from a database URL for structural comparison.

    Using only host, port, and database name prevents false-positive equality
    matches caused by different passwords encoding the same logical destination,
    and avoids exposing credentials in comparison logic.

    Examples:
        'postgresql+psycopg://user:pass@127.0.0.1:5432/mydb' -> '127.0.0.1:5432/mydb'
        'postgresql+psycopg://user:pass@localhost:5432/mydb'  -> 'localhost:5432/mydb'
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port or 5432
        # Strip leading slash from path to get the bare database name
        dbname = parsed.path.lstrip("/").split("?")[0].rstrip("/")
        return f"{host}:{port}/{dbname}"
    except Exception:
        # If parsing fails, fall back to the raw URL for the comparison so
        # that a malformed TEST_POSTGRES_URL never silently bypasses safety.
        return url


@pytest.mark.skipif(
    not TEST_POSTGRES_URL,
    reason=(
        "TEST_POSTGRES_URL is not set. Set it in .env to point at an isolated "
        "test database (e.g. lenny_assistant_test) and restart PostgreSQL before "
        "running integration tests."
    ),
)
class TestPostgresIntegration:
    """PostgreSQL 17 + pgvector integration test suite.

    SAFETY NOTICE
    -------------
    This class executes live DDL and DML operations against a real PostgreSQL
    instance.  It strictly requires a dedicated test database and will raise a
    RuntimeError before touching any data if the safety guards detect that
    TEST_POSTGRES_URL resolves to the same host/port/database as DATABASE_URL
    or if the target database name does not contain the word 'test'.
    """

    @pytest.fixture(scope="class")
    def pg_engine(self):
        """Create and yield a SQLAlchemy engine connected to the test database.

        Safety Guards (both run before any database operation):
            Guard 1: Normalized destination of TEST_POSTGRES_URL must differ
                from normalized destination of DATABASE_URL.
            Guard 2: Database name in TEST_POSTGRES_URL must contain 'test'.

        Schema:
            Tables are created via Base.metadata.create_all() directly on the
            test database.  This does not affect the development database and
            does not require Alembic migrations to have been applied.

        Teardown:
            The engine connection pool is disposed after all tests in the class
            complete.  Tables are NOT dropped; the test database can be recreated
            from scratch by dropping and re-creating lenny_assistant_test.
        """
        # --- Safety Guard 1: destination equality (normalized, credential-free) ---
        test_dest = _extract_db_destination(TEST_POSTGRES_URL)
        dev_dest = _extract_db_destination(DEV_DATABASE_URL)

        if test_dest == dev_dest and dev_dest:
            raise RuntimeError(
                "SAFETY VIOLATION: TEST_POSTGRES_URL and DATABASE_URL resolve to the "
                f"same database destination ({test_dest}). "
                "Integration tests must target an isolated test database "
                "(e.g. lenny_assistant_test) to prevent destructive mutations on "
                "development data. Update TEST_POSTGRES_URL in your .env file."
            )

        # --- Safety Guard 2: database name must contain 'test' ---
        try:
            db_name = urlparse(TEST_POSTGRES_URL).path.lstrip("/").split("?")[0].rstrip("/")
        except Exception:
            db_name = ""

        if "test" not in db_name.lower():
            raise RuntimeError(
                f"SAFETY VIOLATION: Target database name '{db_name}' does not contain "
                "'test'. Set TEST_POSTGRES_URL to a dedicated test database "
                "(e.g. lenny_assistant_test) in your .env file."
            )

        # --- Create engine and ensure schema exists on the test database ---
        engine = create_engine(TEST_POSTGRES_URL)
        from backend.app.database import Base
        Base.metadata.create_all(bind=engine)

        yield engine

        engine.dispose()

    # -----------------------------------------------------------------------
    # Tests
    # -----------------------------------------------------------------------

    def test_postgres_connection_and_version(self, pg_engine):
        """Verify connection to PostgreSQL and confirm server version string.

        Record Mutation: None (read-only query).
        """
        with pg_engine.connect() as conn:
            result = conn.execute(text("SELECT version();")).scalar()
            assert result is not None
            assert "PostgreSQL" in result

    def test_postgres_native_uuid_and_jsonb(self, pg_engine):
        """Verify native PostgreSQL UUID handling and JSONB field indexing.

        Record Mutation: Creates 1 ChatSession row, queries it using a JSONB
        operator, then deletes the row in an explicit cleanup step.
        """
        with Session(pg_engine) as session:
            test_session = ChatSession(
                id=uuid.uuid4(),
                title="PostgreSQL Native Test",
                user_metadata={"tier": "enterprise", "features": ["rag", "ship30"]},
            )
            session.add(test_session)
            session.commit()

            retrieved = session.execute(
                select(ChatSession).where(
                    ChatSession.user_metadata["tier"].as_string() == "enterprise"
                )
            ).scalar_one_or_none()

            assert retrieved is not None
            assert retrieved.title == "PostgreSQL Native Test"

            # Explicit cleanup — do not rely on teardown to remove test data
            session.delete(retrieved)
            session.commit()

    def test_postgres_cascade_deletion(self, pg_engine):
        """Verify that deleting a session cascades to remove all child messages.

        Record Mutation: Creates 1 ChatSession and 2 ChatMessage rows,
        deletes the ChatSession, and asserts that the ChatMessage rows are
        removed via ON DELETE CASCADE.
        """
        with Session(pg_engine) as session:
            sess = ChatSession(title="Cascade Parent Session")
            session.add(sess)
            session.commit()

            msg1 = ChatMessage(session_id=sess.id, role="user", content="Question 1")
            msg2 = ChatMessage(session_id=sess.id, role="user", content="Question 2")
            session.add_all([msg1, msg2])
            session.commit()

            session.delete(sess)
            session.commit()

            remaining = session.execute(
                select(ChatMessage).where(ChatMessage.session_id == sess.id)
            ).scalars().all()
            assert len(remaining) == 0

    def test_postgres_pgvector_similarity_search(self, pg_engine):
        """Verify native PostgreSQL pgvector cosine distance similarity search (<=>).

        Record Mutation: Creates 1 PodcastEpisode, 1 TranscriptChunk, and
        1 TranscriptEmbedding with a 768-D vector, executes semantic_search,
        asserts distance and similarity score calculation, and cleans up records.
        """
        import math
        from backend.app.models.episode import PodcastEpisode
        from backend.app.models.chunk import TranscriptChunk
        from backend.app.models.embedding import TranscriptEmbedding
        from backend.app.repositories.embedding_repository import semantic_search

        vector_data = [round(math.sin(0.1 + i * 0.01), 6) for i in range(768)]
        query_vector = list(vector_data)  # exact match -> distance ~0.0, similarity ~1.0

        with Session(pg_engine) as session:
            episode = PodcastEpisode(
                slug=f"test-pgvector-episode-{uuid.uuid4().hex[:8]}",
                title="PGVector Test Episode",
                guest="Vector Guest",
                youtube_url="https://www.youtube.com/watch?v=pgvector123",
            )
            session.add(episode)
            session.flush()

            chunk = TranscriptChunk(
                episode_id=episode.id,
                chunk_index=0,
                content="This is a test transcript chunk for pgvector cosine distance search.",
                start_char=0,
                end_char=70,
                start_seconds=120.0,
                end_seconds=130.0,
            )
            session.add(chunk)
            session.flush()

            embedding = TranscriptEmbedding(
                chunk_id=chunk.id,
                model="nomic-embed-text",
                dimensions=768,
                embedding=vector_data,
            )
            session.add(embedding)
            session.commit()

            try:
                results = semantic_search(
                    session=session,
                    query_vector=query_vector,
                    top_k=5,
                    model="nomic-embed-text",
                )
                assert len(results) >= 1
                matched_chunk, matched_episode, distance, similarity = results[0]
                assert matched_chunk.id == chunk.id
                assert matched_episode.id == episode.id
                assert distance < 1e-4
                assert similarity > 0.999
            finally:
                session.delete(embedding)
                session.delete(chunk)
                session.delete(episode)
                session.commit()

