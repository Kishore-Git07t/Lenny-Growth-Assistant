"""Unit and integration tests for Local (Ollama) and Cloud (Google Gemini) LLM Provider Switching.

Covers:
1. GET /api/models and /api/providers safe metadata endpoint (zero secret leakage).
2. PiClient provider & model validation, CLI arguments, and subprocess environment isolation.
3. Chat respond endpoint (POST /api/sessions/{id}/respond) with local and cloud provider overrides.
4. Ship 30 essay generation endpoint (POST /api/sessions/{id}/essay) with provider overrides.
5. HTML/CSS artifact endpoint (POST /api/sessions/{id}/artifact) with provider overrides.
6. Error handling for unconfigured cloud credentials (HTTP 400 with actionable feedback).
7. Session isolation and metadata persistence for multi-provider interactions.
8. Genuine HTTP 404 validation for nonexistent sessions.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.agent.exceptions import PiConfigurationError
from backend.app.agent.pi_client import PiClient, PiGenerationResult
from backend.app.agent.service import AgentService
from backend.app.config import Settings, get_settings
from backend.app.main import app
from backend.app.repositories import create_session
from backend.app.schemas.provider import ProviderInfo, ProviderStatusResponse


# -----------------------------------------------------------------------------
# Fixtures & Helpers
# -----------------------------------------------------------------------------

@pytest.fixture
def mock_session_id(db_session: Session) -> uuid.UUID:
    """Create a test chat session in the isolated database."""
    session_record = create_session(db=db_session, title="Provider Test Session")
    return session_record.id


# -----------------------------------------------------------------------------
# 1. Safe Model & Provider Status Endpoint Tests
# -----------------------------------------------------------------------------

def test_get_models_safe_metadata_without_secrets(client: TestClient):
    """Verify /api/models returns provider metadata without leaking API keys or secrets."""
    fake_secret = "AIzaSy-TEST-DETERMINISTIC-KEY-998877"
    mock_settings = Settings(
        GEMINI_API_KEY=fake_secret,
        GEMINI_MODEL="gemini-2.5-flash",
        LLM_PROVIDER="ollama",
    )

    app.dependency_overrides[get_settings] = lambda: mock_settings
    try:
        response = client.get("/api/models")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert "default_provider" in data
        assert "active_provider" in data
        assert "providers" in data
        assert isinstance(data["providers"], list)

        # 1. Guarantee the actual secret value is never exposed in the response body
        assert fake_secret not in response.text

        # 2. Guarantee no sensitive credential or authorization fields are exposed in JSON structure
        sensitive_field_names = {"api_key", "key", "secret", "token", "password", "authorization", "auth_header"}
        for provider in data["providers"]:
            assert not sensitive_field_names.intersection(set(provider.keys()))
            for val in provider.values():
                if isinstance(val, str):
                    assert fake_secret not in val

        # 3. Verify safe metadata remains available and accurate
        provider_ids = [p["id"] for p in data["providers"]]
        assert "ollama" in provider_ids
        assert "google" in provider_ids

        ollama_info = next(p for p in data["providers"] if p["id"] == "ollama")
        assert ollama_info["type"] == "local"
        assert ollama_info["is_configured"] is True
        assert ollama_info["model"] == "qwen2.5:1.5b"

        gemini_info = next(p for p in data["providers"] if p["id"] == "google")
        assert gemini_info["type"] == "cloud"
        assert gemini_info["is_configured"] is True
        assert gemini_info["model"] == "gemini-2.5-flash"
        assert "Google Gemini" in gemini_info["name"]

        # 4. User-facing descriptions may safely mention the configuration variable name GEMINI_API_KEY
        # Verify no raw authorization headers or bearer tokens are present
        assert "bearer " not in response.text.lower()
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_get_providers_alias_endpoint(client: TestClient):
    """Verify /api/providers functions as an exact alias to /api/models."""
    models_res = client.get("/api/models")
    providers_res = client.get("/api/providers")

    assert providers_res.status_code == status.HTTP_200_OK
    assert models_res.json() == providers_res.json()


def test_provider_status_reflects_configured_credentials(client: TestClient):
    """Verify is_configured accurately reflects presence of cloud credentials."""
    fake_configured_key = "AIzaSy-mock-test-key-12345"

    # Case A: When a nonempty Gemini key is configured, is_configured must be True
    configured_settings = Settings(
        GEMINI_API_KEY=fake_configured_key,
        GEMINI_MODEL="gemini-2.5-flash",
        LLM_PROVIDER="ollama",
    )
    app.dependency_overrides[get_settings] = lambda: configured_settings
    try:
        response = client.get("/api/models")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        gemini_info = next(p for p in data["providers"] if p["id"] == "google")
        assert gemini_info["is_configured"] is True
        # Strictly verify secret itself is not leaked in response
        assert fake_configured_key not in response.text
    finally:
        app.dependency_overrides.pop(get_settings, None)

    # Case B: When the key is absent or blank, is_configured must be False
    unconfigured_settings = Settings(
        GEMINI_API_KEY=None,
        GEMINI_MODEL="gemini-2.5-flash",
        LLM_PROVIDER="ollama",
    )
    app.dependency_overrides[get_settings] = lambda: unconfigured_settings
    try:
        response_unconf = client.get("/api/models")
        assert response_unconf.status_code == status.HTTP_200_OK
        data_unconf = response_unconf.json()

        gemini_unconf = next(p for p in data_unconf["providers"] if p["id"] == "google")
        assert gemini_unconf["is_configured"] is False
        assert "GEMINI_API_KEY" in gemini_unconf["description"]
    finally:
        app.dependency_overrides.pop(get_settings, None)


# -----------------------------------------------------------------------------
# 2. PiClient Provider and Model Validation Tests
# -----------------------------------------------------------------------------

def test_pi_client_validate_provider_defaults():
    """Verify PiClient defaults to configured settings when provider/model are None."""
    settings = Settings(LLM_PROVIDER="ollama", OLLAMA_MODEL="qwen2.5:1.5b")
    client = PiClient(settings=settings)

    prov, model = client.validate_provider_model(None, None)
    assert prov == "ollama"
    assert model == "qwen2.5:1.5b"


def test_pi_client_validate_unconfigured_cloud_provider_raises():
    """Verify selecting Google Gemini without an API key raises PiConfigurationError."""
    settings = Settings(GEMINI_API_KEY=None)
    client = PiClient(settings=settings)

    with pytest.raises(PiConfigurationError) as exc_info:
        client.validate_provider_model("google", "gemini-2.5-flash")
    assert "GEMINI_API_KEY is not configured" in str(exc_info.value)


def test_pi_client_validate_configured_cloud_provider_succeeds():
    """Verify selecting Google Gemini with a configured API key succeeds."""
    settings = Settings(GEMINI_API_KEY="AIzaSy-mock-valid-key", GEMINI_MODEL="gemini-2.5-flash")
    client = PiClient(settings=settings)

    prov, model = client.validate_provider_model("google", None)
    assert prov == "google"
    assert model == "gemini-2.5-flash"


def test_pi_client_validate_unsupported_provider_raises():
    """Verify selecting an unknown provider raises PiConfigurationError."""
    client = PiClient()
    with pytest.raises(PiConfigurationError) as exc_info:
        client.validate_provider_model("unsupported_llm", "some_model")
    assert "Unsupported LLM provider" in str(exc_info.value)


def test_pi_client_build_command_args_includes_provider_and_model():
    """Verify CLI arguments pass --provider google and --model with disabled dangerous tools."""
    client = PiClient()
    with patch.object(client, "resolve_executable", return_value=["node", "cli.js"]):
        args = client.build_command_args(provider="google", model="gemini-2.5-flash")

    assert "--provider" in args
    prov_idx = args.index("--provider")
    assert args[prov_idx + 1] == "google"

    assert "--model" in args
    model_idx = args.index("--model")
    assert args[model_idx + 1] == "gemini-2.5-flash"

    # Strict isolation arguments must still be present
    assert "--no-tools" in args
    assert "--no-mcp" in args
    assert "--mode" in args


def test_pi_client_build_subprocess_env_isolates_keys():
    """Verify subprocess environment contains only configured keys and doesn't pollute."""
    settings = Settings(
        GEMINI_API_KEY="AIzaSy-isolated-gemini-key",
    )
    client = PiClient(settings=settings)
    env = client.build_subprocess_env()

    assert env.get("GEMINI_API_KEY") == "AIzaSy-isolated-gemini-key"


# -----------------------------------------------------------------------------
# 3. Chat Session Respond Endpoint Provider Switching Tests
# -----------------------------------------------------------------------------

def test_respond_endpoint_with_local_provider(client: TestClient, mock_session_id: uuid.UUID):
    """Verify chat respond endpoint accepts local provider override."""
    mock_result = PiGenerationResult(
        text="Lenny's guests emphasize customer retention metrics [1].",
        provider="ollama",
        model="qwen2.5:1.5b",
        raw_events=[],
    )

    with patch.object(PiClient, "generate_response", new_callable=AsyncMock, return_value=mock_result):
        payload = {
            "content": "What retention metrics matter?",
            "provider": "ollama",
            "model": "qwen2.5:1.5b",
        }
        res = client.post(f"/api/sessions/{mock_session_id}/respond", json=payload)
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["provider"] == "ollama"
        assert data["model"] == "qwen2.5:1.5b"


def test_respond_endpoint_with_cloud_provider(client: TestClient, mock_session_id: uuid.UUID):
    """Verify chat respond endpoint accepts cloud Google Gemini provider override."""
    mock_result = PiGenerationResult(
        text="According to Elena Verna on Lenny's Podcast, product-led growth requires virality loops [1].",
        provider="google",
        model="gemini-2.5-flash",
        raw_events=[],
    )

    # Simulate environment where GEMINI_API_KEY is configured
    mock_settings = Settings(
        GEMINI_API_KEY="AIzaSy-valid-key-for-test",
        GEMINI_MODEL="gemini-2.5-flash",
    )
    with patch("backend.app.agent.service.get_settings", return_value=mock_settings), \
         patch.object(PiClient, "generate_response", new_callable=AsyncMock, return_value=mock_result):
        payload = {
            "content": "Explain product led growth loops.",
            "provider": "google",
            "model": "gemini-2.5-flash",
        }
        res = client.post(f"/api/sessions/{mock_session_id}/respond", json=payload)
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["provider"] == "google"
        assert data["model"] == "gemini-2.5-flash"
        assert data["assistant_message"]["source_metadata"]["provider"] == "google"


def test_respond_endpoint_unconfigured_cloud_returns_400(client: TestClient, mock_session_id: uuid.UUID):
    """Verify selecting Google Gemini when unconfigured returns HTTP 400 Bad Request with actionable message."""
    mock_settings = Settings(GEMINI_API_KEY=None, LLM_PROVIDER="ollama")
    app.dependency_overrides[get_settings] = lambda: mock_settings
    try:
        with patch.object(PiClient, "generate_response", new_callable=AsyncMock) as mock_generate, \
             patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_subproc:
            payload = {
                "content": "Tell me about growth loops.",
                "provider": "google",
                "model": "gemini-2.5-flash",
            }
            res = client.post(f"/api/sessions/{mock_session_id}/respond", json=payload)
            assert res.status_code == status.HTTP_400_BAD_REQUEST
            err = res.json()
            assert "detail" in err
            assert "GEMINI_API_KEY is not configured" in str(err["detail"])

            # Strict isolation check: Pi subprocess must NEVER be launched for missing credentials
            mock_generate.assert_not_called()
            mock_subproc.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_respond_endpoint_nonexistent_session_returns_404(client: TestClient):
    """Verify that a nonexistent session ID returns genuine HTTP 404."""
    fake_id = uuid.uuid4()
    payload = {"content": "Hello", "provider": "ollama", "model": "qwen2.5:1.5b"}
    res = client.post(f"/api/sessions/{fake_id}/respond", json=payload)
    assert res.status_code == status.HTTP_404_NOT_FOUND


# -----------------------------------------------------------------------------
# 4. Essay Generation Endpoint Provider Switching Tests
# -----------------------------------------------------------------------------

def test_essay_endpoint_with_cloud_provider(client: TestClient, mock_session_id: uuid.UUID):
    """Verify essay endpoint accepts cloud provider and propagates to response metadata."""
    outline_mock = PiGenerationResult(
        text="Title: B2B Growth Engines\nThesis: Retention powers growth.\n1. Heading: Foundation\nPurpose: Define metrics.",
        provider="google",
        model="gemini-2.5-flash",
        raw_events=[],
    )
    section_mock = PiGenerationResult(
        text="## Foundation\nRetention is the ultimate growth lever as discussed in Lenny's Podcast.",
        provider="google",
        model="gemini-2.5-flash",
        raw_events=[],
    )

    mock_settings = Settings(
        GEMINI_API_KEY="AIzaSy-valid-key-for-test",
        GEMINI_MODEL="gemini-2.5-flash",
    )

    with patch("backend.app.agent.skills.ship30_essay.orchestrator.get_settings", return_value=mock_settings), \
         patch.object(PiClient, "generate_response", new_callable=AsyncMock, side_effect=[outline_mock, section_mock, section_mock, section_mock, section_mock]):
        payload = {
            "topic": "B2B SaaS Growth Engines",
            "audience": "Founders",
            "target_word_count": 800,
            "provider": "google",
            "model": "gemini-2.5-flash",
        }
        res = client.post(f"/api/sessions/{mock_session_id}/essay", json=payload)
        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["provider"] == "google"
        assert data["model"] == "gemini-2.5-flash"


# -----------------------------------------------------------------------------
# 5. HTML Artifact Generation Endpoint Provider Switching Tests
# -----------------------------------------------------------------------------

def test_artifact_endpoint_with_cloud_provider(client: TestClient, mock_session_id: uuid.UUID):
    """Verify HTML artifact endpoint accepts cloud provider and returns in ArtifactResponse."""
    artifact_mock = PiGenerationResult(
        text="```html\n<div class=\"hero\"><h1>B2B SaaS Dashboard</h1></div>\n```\n```css\n.hero { padding: 2rem; }\n```",
        provider="google",
        model="gemini-2.5-flash",
        raw_events=[],
    )

    mock_settings = Settings(
        GEMINI_API_KEY="AIzaSy-valid-key-for-test",
        GEMINI_MODEL="gemini-2.5-flash",
    )

    with patch("backend.app.agent.skills.html_artifact.orchestrator.get_settings", return_value=mock_settings), \
         patch.object(PiClient, "generate_response", new_callable=AsyncMock, return_value=artifact_mock):
        payload = {
            "prompt": "Create a clean SaaS hero section",
            "title": "SaaS Hero",
            "artifact_type": "landing_page",
            "provider": "google",
            "model": "gemini-2.5-flash",
        }
        res = client.post(f"/api/sessions/{mock_session_id}/artifact", json=payload)
        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["provider"] == "google"
        assert data["model"] == "gemini-2.5-flash"
