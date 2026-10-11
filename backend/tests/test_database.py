"""Unit tests for database readiness and connection failure handling."""

from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.app.database import (
    DatabaseUnavailableException,
    DatabaseUnconfiguredException,
    get_db,
)
from backend.app.main import app


def test_readiness_when_connected() -> None:
    """Verify that GET /api/ready returns HTTP 200 when database connectivity check succeeds."""
    with patch("backend.app.routes.ready.check_db_connectivity", return_value=(True, "connected")):
        client = TestClient(app)
        response = client.get("/api/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["database"] == "connected"


def test_readiness_when_unconfigured() -> None:
    """Verify that GET /api/ready returns HTTP 503 when DATABASE_URL is not set."""
    with patch("backend.app.routes.ready.check_db_connectivity", return_value=(False, "unconfigured")):
        client = TestClient(app)
        response = client.get("/api/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["database"] == "unconfigured"


def test_readiness_when_unavailable() -> None:
    """Verify that GET /api/ready returns HTTP 503 when database connection fails."""
    with patch(
        "backend.app.routes.ready.check_db_connectivity",
        return_value=(False, "Connection refused to port 5432"),
    ):
        client = TestClient(app)
        response = client.get("/api/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["database"] == "unavailable"
        assert "Connection refused" in data["detail"]


def test_database_unconfigured_exception_handling() -> None:
    """Verify that endpoints raise structured HTTP 503 when database is unconfigured."""
    def raise_unconfigured():
        raise DatabaseUnconfiguredException("Database is not configured.")

    app.dependency_overrides[get_db] = raise_unconfigured
    client = TestClient(app)
    try:
        response = client.get("/api/sessions")
        assert response.status_code == 503
        data = response.json()
        assert data["error"] == "database_unconfigured"
        assert data["status_code"] == 503
    finally:
        app.dependency_overrides.clear()


def test_database_unavailable_exception_handling() -> None:
    """Verify that endpoints raise structured HTTP 503 when database connection drops."""
    def raise_unavailable():
        raise DatabaseUnavailableException("OperationalError: server closed the connection unexpectedly")

    app.dependency_overrides[get_db] = raise_unavailable
    client = TestClient(app)
    try:
        response = client.post("/api/sessions", json={"title": "Test Session"})
        assert response.status_code == 503
        data = response.json()
        assert data["error"] == "database_unavailable"
        assert data["status_code"] == 503
    finally:
        app.dependency_overrides.clear()
