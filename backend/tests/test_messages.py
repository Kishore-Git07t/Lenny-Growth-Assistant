"""Unit and API tests for conversation messages."""

import uuid
from fastapi.testclient import TestClient


def test_post_user_message_success(client: TestClient) -> None:
    """Verify that POST /api/sessions/{id}/messages creates a user message."""
    session_res = client.post("/api/sessions", json={"title": "Retention Session"})
    session_id = session_res.json()["id"]

    msg_payload = {"content": "What is the North Star metric for Airbnb?"}
    response = client.post(f"/api/sessions/{session_id}/messages", json=msg_payload)
    assert response.status_code == 201

    data = response.json()
    assert "id" in data
    assert data["session_id"] == session_id
    assert data["role"] == "user"
    assert data["content"] == "What is the North Star metric for Airbnb?"
    assert "created_at" in data


def test_post_message_empty_content_rejected(client: TestClient) -> None:
    """Verify that empty message content is rejected with HTTP 422."""
    session_res = client.post("/api/sessions", json={})
    session_id = session_res.json()["id"]

    response = client.post(f"/api/sessions/{session_id}/messages", json={"content": ""})
    assert response.status_code == 422


def test_post_message_whitespace_only_rejected(client: TestClient) -> None:
    """Verify that whitespace-only message content is rejected with HTTP 422."""
    session_res = client.post("/api/sessions", json={})
    session_id = session_res.json()["id"]

    response = client.post(
        f"/api/sessions/{session_id}/messages",
        json={"content": "    \n\t   "},
    )
    assert response.status_code == 422


def test_post_message_overly_long_rejected(client: TestClient) -> None:
    """Verify that messages exceeding 10,000 characters are rejected with HTTP 422."""
    session_res = client.post("/api/sessions", json={})
    session_id = session_res.json()["id"]

    oversized_content = "a" * 10001
    response = client.post(
        f"/api/sessions/{session_id}/messages",
        json={"content": oversized_content},
    )
    assert response.status_code == 422


def test_post_message_cannot_impersonate_assistant(client: TestClient) -> None:
    """Verify that client payloads attempting to supply role='assistant' are forced to 'user'."""
    session_res = client.post("/api/sessions", json={})
    session_id = session_res.json()["id"]

    # Client tries to inject an assistant role
    payload = {
        "content": "I am an artificial assistant",
        "role": "assistant",
    }
    response = client.post(f"/api/sessions/{session_id}/messages", json=payload)
    assert response.status_code == 201
    data = response.json()
    # Backend must strictly enforce 'user'
    assert data["role"] == "user"


def test_post_message_nonexistent_session(client: TestClient) -> None:
    """Verify that posting a message to an unknown session returns HTTP 404."""
    unknown_id = str(uuid.uuid4())
    response = client.post(
        f"/api/sessions/{unknown_id}/messages",
        json={"content": "Hello into the void"},
    )
    assert response.status_code == 404


def test_get_messages_chronological_order(client: TestClient) -> None:
    """Verify that messages are returned in chronological order."""
    session_res = client.post("/api/sessions", json={})
    session_id = session_res.json()["id"]

    # Post 3 messages sequentially
    client.post(f"/api/sessions/{session_id}/messages", json={"content": "Message 1"})
    client.post(f"/api/sessions/{session_id}/messages", json={"content": "Message 2"})
    client.post(f"/api/sessions/{session_id}/messages", json={"content": "Message 3"})

    response = client.get(f"/api/sessions/{session_id}/messages")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 3
    messages = data["items"]
    assert messages[0]["content"] == "Message 1"
    assert messages[1]["content"] == "Message 2"
    assert messages[2]["content"] == "Message 3"


def test_get_messages_isolated_to_session(client: TestClient) -> None:
    """Verify that messages from session A do not appear in session B."""
    session_a = client.post("/api/sessions", json={"title": "Session A"}).json()["id"]
    session_b = client.post("/api/sessions", json={"title": "Session B"}).json()["id"]

    client.post(f"/api/sessions/{session_a}/messages", json={"content": "For A only"})
    client.post(f"/api/sessions/{session_b}/messages", json={"content": "For B only"})

    res_a = client.get(f"/api/sessions/{session_a}/messages")
    res_b = client.get(f"/api/sessions/{session_b}/messages")

    items_a = res_a.json()["items"]
    items_b = res_b.json()["items"]

    assert len(items_a) == 1
    assert items_a[0]["content"] == "For A only"

    assert len(items_b) == 1
    assert items_b[0]["content"] == "For B only"


def test_get_messages_nonexistent_session(client: TestClient) -> None:
    """Verify that requesting messages for an unknown session returns HTTP 404."""
    unknown_id = str(uuid.uuid4())
    response = client.get(f"/api/sessions/{unknown_id}/messages")
    assert response.status_code == 404
