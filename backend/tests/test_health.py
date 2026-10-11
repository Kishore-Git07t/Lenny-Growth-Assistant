"""Automated tests for FastAPI health endpoint.

Tests verify the health probe payload structure, operational database reporting (Phase 2+),
and graceful fallback reporting when database is unconfigured or unavailable.
"""

from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_health_endpoint_status_code() -> None:
    """Verify that GET /api/health returns HTTP 200."""
    response = client.get("/api/health")
    assert response.status_code == 200


def test_health_endpoint_payload_structure() -> None:
    """Verify that GET /api/health returns required structured fields with operational database."""
    with patch("backend.app.main.check_db_connectivity", return_value=(True, "connected")):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "ok"
        assert data["service"] == "lenny-growth-assistant-backend"
        assert "version" in data
        assert "timestamp" in data
        assert "environment" in data
        assert "llm_provider" in data
        assert "model" in data
        assert isinstance(data["components"], dict)
        assert data["components"]["api"] == "operational"
        assert data["components"]["database"] == "operational"
        assert "not checked" in data["components"]["ollama"]
        assert "not configured" in data["components"]["agent_runtime"]


def test_health_endpoint_when_database_unconfigured() -> None:
    """Verify that GET /api/health preserves liveness and reports unconfigured when database is not set."""
    with patch("backend.app.main.check_db_connectivity", return_value=(False, "unconfigured")):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "not configured" in data["components"]["database"]


def test_health_endpoint_when_database_unavailable() -> None:
    """Verify that GET /api/health preserves liveness and reports unavailable when database check fails."""
    with patch("backend.app.main.check_db_connectivity", return_value=(False, "connection timeout")):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["components"]["database"].startswith("unavailable")


def test_root_endpoint_returns_service_info() -> None:
    """Verify that GET / returns service information and docs links."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "docs" in data
    assert "health" in data

