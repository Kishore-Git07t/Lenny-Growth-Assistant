"""Unit and API tests for conversation sessions."""

import uuid
from fastapi.testclient import TestClient


def test_create_session_success(client: TestClient) -> None:
    """Verify that POST /api/sessions creates a session with title and metadata."""
    payload = {
        "title": "PLG and Free Trials",
        "user_metadata": {"topic": "growth", "source": "test"},
    }
    response = client.post("/api/sessions", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert "id" in data
    assert uuid.UUID(data["id"])
    assert data["title"] == "PLG and Free Trials"
    assert data["user_metadata"] == {"topic": "growth", "source": "test"}
    assert "created_at" in data
    assert "updated_at" in data


def test_create_session_defaults(client: TestClient) -> None:
    """Verify that POST /api/sessions creates a session with default None title and empty metadata."""
    response = client.post("/api/sessions", json={})
    assert response.status_code == 201

    data = response.json()
    assert data["title"] is None
    assert data["user_metadata"] == {}
    assert "id" in data


def test_create_session_bounded_metadata_rejection(client: TestClient) -> None:
    """Verify that metadata exceeding 50 keys is rejected with HTTP 422."""
    oversized_metadata = {f"key_{i}": f"val_{i}" for i in range(51)}
    response = client.post("/api/sessions", json={"user_metadata": oversized_metadata})
    assert response.status_code == 422


def test_list_sessions_empty(client: TestClient) -> None:
    """Verify that GET /api/sessions returns an empty list when no sessions exist."""
    response = client.get("/api/sessions")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data["items"], list)
    assert data["total"] == 0
    assert data["limit"] == 20
    assert data["offset"] == 0


def test_list_sessions_paginated(client: TestClient) -> None:
    """Verify pagination behavior on GET /api/sessions."""
    # Create 5 sessions
    for i in range(5):
        client.post("/api/sessions", json={"title": f"Session {i}"})

    # Fetch page with limit 2, offset 2
    response = client.get("/api/sessions?limit=2&offset=2")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["limit"] == 2
    assert data["offset"] == 2


def test_get_session_by_id_success(client: TestClient) -> None:
    """Verify that GET /api/sessions/{session_id} retrieves an existing session."""
    create_res = client.post("/api/sessions", json={"title": "Pricing Tactics"})
    session_id = create_res.json()["id"]

    response = client.get(f"/api/sessions/{session_id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == session_id
    assert data["title"] == "Pricing Tactics"


def test_get_session_by_id_not_found(client: TestClient) -> None:
    """Verify that GET /api/sessions/{session_id} returns 404 for unknown UUID."""
    unknown_id = str(uuid.uuid4())
    response = client.get(f"/api/sessions/{unknown_id}")
    assert response.status_code == 404
    assert f"'{unknown_id}' not found" in response.json()["detail"]


def test_get_session_invalid_uuid(client: TestClient) -> None:
    """Verify that GET /api/sessions/{session_id} returns 422 for malformed UUID string."""
    response = client.get("/api/sessions/not-a-valid-uuid")
    assert response.status_code == 422


def test_update_session_title_success(client: TestClient) -> None:
    """Verify that PATCH /api/sessions/{session_id} updates and persists the session title."""
    create_res = client.post("/api/sessions", json={})
    assert create_res.status_code == 201
    session_id = create_res.json()["id"]
    assert create_res.json()["title"] is None

    patch_res = client.patch(
        f"/api/sessions/{session_id}",
        json={"title": "When to hire sales according to Jason Lemkin"},
    )
    assert patch_res.status_code == 200
    data = patch_res.json()
    assert data["id"] == session_id
    assert data["title"] == "When to hire sales according to Jason Lemkin"

    # Verify title persists on subsequent GET
    get_res = client.get(f"/api/sessions/{session_id}")
    assert get_res.status_code == 200
    assert get_res.json()["title"] == "When to hire sales according to Jason Lemkin"


def test_update_session_not_found(client: TestClient) -> None:
    """Verify that PATCH /api/sessions/{session_id} returns 404 for unknown session ID."""
    unknown_id = str(uuid.uuid4())
    patch_res = client.patch(
        f"/api/sessions/{unknown_id}",
        json={"title": "Non-existent session title"},
    )
    assert patch_res.status_code == 404


def test_update_session_empty_title_rejection(client: TestClient) -> None:
    """Verify that empty or whitespace-only title update is rejected with 422."""
    create_res = client.post("/api/sessions", json={"title": "Initial Title"})
    session_id = create_res.json()["id"]

    patch_res = client.patch(
        f"/api/sessions/{session_id}",
        json={"title": "   "},
    )
    assert patch_res.status_code == 422


def test_update_session_preserves_messages(client: TestClient) -> None:
    """Verify that updating a session title does not alter session messages or session ID."""
    create_res = client.post("/api/sessions", json={})
    session_id = create_res.json()["id"]

    # Post a message
    msg_res = client.post(
        f"/api/sessions/{session_id}/messages",
        json={"content": "When should founders hire sales?"},
    )
    assert msg_res.status_code == 201

    # Update session title
    patch_res = client.patch(
        f"/api/sessions/{session_id}",
        json={"title": "Sales Hiring Timing"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["id"] == session_id

    # Verify messages are intact
    msgs_res = client.get(f"/api/sessions/{session_id}/messages")
    assert msgs_res.status_code == 200
    items = msgs_res.json()["items"]
    assert len(items) == 1
    assert items[0]["content"] == "When should founders hire sales?"
    assert items[0]["session_id"] == session_id

