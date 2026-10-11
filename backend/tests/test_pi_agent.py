"""Unit and API tests for the Pi Coding Agent integration using mocked subprocesses."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.agent.exceptions import (
    PiAgentException,
    PiAuthenticationError,
    PiConfigurationError,
    PiEmptyResponseError,
    PiModelNotFoundError,
    PiNetworkError,
    PiNotInstalledError,
    PiOutputParseError,
    PiProcessTerminatedError,
    PiPromptRejectedError,
    PiProviderError,
    PiRateLimitError,
    PiTimeoutError,
)
from backend.app.agent.pi_client import PiClient, PiGenerationResult, sanitize_secret_text
from backend.app.agent.service import AgentService, PROTOTYPE_SYSTEM_PROMPT
from backend.app.config import Settings
from backend.app.models.message import ChatMessage
from backend.app.models.session import ChatSession
from backend.app.repositories import create_session, list_messages_by_session


# ---------------------------------------------------------------------------
# Unit tests for PiClient
# ---------------------------------------------------------------------------

def test_pi_disabled_tools_arguments():
    """Verify that build_command_args strictly enforces disabling all dangerous tools."""
    client = PiClient()
    with patch.object(client, "resolve_executable", return_value=["node", "cli.js"]):
        args = client.build_command_args(provider="ollama", model="qwen2.5:1.5b")

    # Command line must strictly contain flags disabling tools and MCP
    assert "--no-tools" in args
    assert "--no-extensions" in args
    assert "--no-skills" in args
    assert "--no-prompt-templates" in args
    assert "--no-mcp" in args
    assert "--no-session" in args
    assert "--provider" in args
    assert "ollama" in args
    assert "--model" in args
    assert "qwen2.5:1.5b" in args


def test_pi_provider_selection_validation():
    """Verify provider validation for local Ollama and cloud providers."""
    client = PiClient()

    # Ollama provider is valid by default
    prov, model = client.validate_provider_configuration("ollama", "qwen2.5:1.5b")
    assert prov == "ollama"
    assert model == "qwen2.5:1.5b"

    # OpenAI without API key raises configuration error
    with patch.object(client.settings, "openai_api_key", None):
        with pytest.raises(PiConfigurationError) as exc_info:
            client.validate_provider_configuration("openai", "gpt-4o-mini")
        assert "OPENAI_API_KEY is not configured" in str(exc_info.value)

    # Anthropic without API key raises configuration error
    with patch.object(client.settings, "anthropic_api_key", None):
        with pytest.raises(PiConfigurationError) as exc_info:
            client.validate_provider_configuration("anthropic", "claude-3-5-sonnet")
        assert "ANTHROPIC_API_KEY is not configured" in str(exc_info.value)

    # Unsupported provider raises configuration error
    with pytest.raises(PiConfigurationError) as exc_info:
        client.validate_provider_configuration("unsupported_llm", "some_model")
    assert "Unsupported LLM provider" in str(exc_info.value)


def test_pi_missing_installation():
    """Verify that PiNotInstalledError is raised with clear instructions when binary is missing."""
    client = PiClient()
    with patch.object(client.settings, "pi_agent_executable", None), \
         patch("shutil.which", return_value=None), \
         patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(PiNotInstalledError) as exc_info:
            client.resolve_executable()
        assert "npm install" in str(exc_info.value)


def _build_mock_subprocess(
    jsonl_lines=None,
    hanging: bool = False,
    stderr_lines=None,
) -> MagicMock:
    """Build a mock asyncio.subprocess.Process with realistic synchronous and asynchronous stream methods.

    Preserves exact asyncio subprocess semantics:
        Synchronous:
            - proc.stdin.write(data) (buffers data in StreamWriter)
            - proc.stdout.at_eof() -> bool
            - proc.stderr.at_eof() -> bool
            - proc.terminate()
            - proc.kill()
            - proc.returncode (int or None attribute)
        Asynchronous:
            - await proc.stdin.drain()
            - await proc.stdout.readline() -> bytes
            - await proc.stderr.readline() -> bytes
            - await proc.wait()
    """
    mock_proc = MagicMock()
    mock_proc.returncode = 0 if not hanging else None
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    # stdin: StreamWriter
    mock_stdin = MagicMock()
    mock_stdin.write = MagicMock()
    mock_stdin.drain = AsyncMock()
    mock_stdin.close = MagicMock()
    mock_stdin.is_closing = MagicMock(return_value=False)
    mock_stdin.wait_closed = AsyncMock()
    mock_proc.stdin = mock_stdin

    # stdout: StreamReader
    mock_stdout = MagicMock()
    if hanging:
        async def hanging_readline() -> bytes:
            await asyncio.sleep(10.0)
            return b""

        mock_stdout.readline = AsyncMock(side_effect=hanging_readline)
        mock_stdout.at_eof = MagicMock(return_value=False)
        mock_stdout.read = AsyncMock(return_value=b"")
    else:
        out_lines = list(jsonl_lines or [])

        async def mock_readline() -> bytes:
            if out_lines:
                return out_lines.pop(0)
            return b""

        mock_stdout.readline = AsyncMock(side_effect=mock_readline)
        mock_stdout.at_eof = MagicMock(side_effect=lambda: len(out_lines) == 0)
        mock_stdout.read = AsyncMock(return_value=b"")
    mock_proc.stdout = mock_stdout

    # stderr: StreamReader
    err_lines = list(stderr_lines or [])
    mock_stderr = MagicMock()

    async def mock_err_readline() -> bytes:
        if err_lines:
            return err_lines.pop(0)
        return b""

    mock_stderr.readline = AsyncMock(side_effect=mock_err_readline)
    mock_stderr.at_eof = MagicMock(side_effect=lambda: len(err_lines) == 0)
    mock_proc.stderr = mock_stderr

    # transport: BaseSubprocessTransport
    mock_transport = MagicMock()
    mock_transport.is_closing = MagicMock(return_value=False)
    mock_transport.close = MagicMock()
    mock_proc._transport = mock_transport

    return mock_proc


@pytest.mark.asyncio
async def test_pi_prompt_acceptance_vs_settled_completion():
    """Verify distinction between prompt acknowledgment and final settled agent completion."""
    client = PiClient()
    req_id = "req-123"

    # Simulated JSONL stream:
    # 1. Prompt acknowledgment (success: true) - NOT completion
    # 2. Agent start
    # 3. Message end with assistant text
    # 4. Agent settled - triggers actual completion
    jsonl_lines = [
        json.dumps({"type": "response", "command": "prompt", "id": req_id, "success": True, "data": {"disposition": "started"}}).encode() + b"\n",
        json.dumps({"type": "agent_start"}).encode() + b"\n",
        json.dumps({
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Elena Verna advocates for Product-Led Sales."}],
            },
        }).encode() + b"\n",
        json.dumps({"type": "agent_settled", "aborted": False}).encode() + b"\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch("uuid.uuid4", return_value=MagicMock(hex="123")), \
         patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await client.generate_response(prompt="Hello", provider="ollama", model="qwen2.5:1.5b")

    assert result.text == "Elena Verna advocates for Product-Led Sales."
    assert result.provider == "ollama"
    assert result.model == "qwen2.5:1.5b"


@pytest.mark.asyncio
async def test_pi_prompt_rejected():
    """Verify that an explicit prompt rejection (success: false) raises PiPromptRejectedError."""
    client = PiClient()
    req_id = "req-rej"

    jsonl_lines = [
        json.dumps({"type": "response", "command": "prompt", "id": req_id, "success": False, "error": "Context window exceeded"}).encode() + b"\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch("uuid.uuid4", return_value=MagicMock(hex="rej")), \
         patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiPromptRejectedError) as exc_info:
            await client.generate_response(prompt="Hello", provider="ollama", model="qwen2.5:1.5b")
        assert "Context window exceeded" in str(exc_info.value)


@pytest.mark.asyncio
async def test_pi_malformed_jsonl_output():
    """Verify that malformed or non-JSON output from stdout raises PiOutputParseError."""
    client = PiClient()

    jsonl_lines = [
        b"INTERNAL_FATAL_ERROR: Unexpected token < in JSON at position 0\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiOutputParseError):
            await client.generate_response(prompt="Hello", provider="ollama", model="qwen2.5:1.5b")


@pytest.mark.asyncio
async def test_pi_timeout_behavior():
    """Verify that a hanging generation run raises PiTimeoutError and terminates the process."""
    client = PiClient()
    mock_proc = _build_mock_subprocess(hanging=True)

    with patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiTimeoutError) as exc_info:
            await client.generate_response(prompt="Hello", provider="ollama", model="qwen2.5:1.5b", timeout_seconds=1)
        assert "timed out" in str(exc_info.value)
        mock_proc.terminate.assert_called()


@pytest.mark.asyncio
async def test_pi_unexpected_process_termination():
    """Verify that an early EOF after prompt acceptance but before agent_settled raises PiProcessTerminatedError."""
    client = PiClient()
    req_id = "req-eof"

    # Prompt accepted, but process closes before completion
    jsonl_lines = [
        json.dumps({"type": "response", "command": "prompt", "id": req_id, "success": True}).encode() + b"\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch("uuid.uuid4", return_value=MagicMock(hex="eof")), \
         patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiProcessTerminatedError) as exc_info:
            await client.generate_response(prompt="Hello", provider="ollama", model="qwen2.5:1.5b")
        assert "before settling" in str(exc_info.value)


@pytest.mark.asyncio
async def test_pi_unexpected_eof_before_acceptance():
    """Verify that an immediate EOF before receiving any prompt response raises PiProcessTerminatedError."""
    client = PiClient()
    mock_proc = _build_mock_subprocess([])

    with patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiProcessTerminatedError) as exc_info:
            await client.generate_response(prompt="Hello", provider="ollama", model="qwen2.5:1.5b")
        assert "without accepting the prompt command" in str(exc_info.value)


@pytest.mark.asyncio
async def test_pi_command_id_correlation():
    """Verify that prompt responses with mismatched request IDs are ignored."""
    client = PiClient()

    # First response has a mismatched ID, then process closes without accepting the prompt
    jsonl_lines = [
        json.dumps({"type": "response", "command": "prompt", "id": "req-mismatched", "success": True}).encode() + b"\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch("uuid.uuid4", return_value=MagicMock(hex="matched")), \
         patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiProcessTerminatedError) as exc_info:
            await client.generate_response(prompt="Hello", provider="ollama", model="qwen2.5:1.5b")
        assert "without accepting the prompt command" in str(exc_info.value)


@pytest.mark.asyncio
async def test_pi_cleanup_on_successful_completion():
    """Verify that successful generation cleanly closes stdin, drains pipes, and closes transport."""
    client = PiClient()
    req_id = "req-clean-ok"

    jsonl_lines = [
        json.dumps({"type": "response", "command": "prompt", "id": req_id, "success": True}).encode() + b"\n",
        json.dumps({
            "type": "message_end",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Net revenue retention is key."}]},
        }).encode() + b"\n",
        json.dumps({"type": "agent_settled"}).encode() + b"\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch("uuid.uuid4", return_value=MagicMock(hex="clean-ok")), \
         patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await client.generate_response(prompt="Test retention", provider="ollama", model="qwen2.5:1.5b")

    assert result.text == "Net revenue retention is key."
    mock_proc.stdin.close.assert_called_once()
    mock_proc.stdin.wait_closed.assert_called_once()
    mock_proc.stdout.at_eof.assert_called()
    mock_proc.stdout.read.assert_not_called()
    mock_proc._transport.close.assert_called_once()
    mock_proc.terminate.assert_not_called()


@pytest.mark.asyncio
async def test_pi_cleanup_drains_unread_stdout_data():
    """Verify that when stdout has unread trailing data (not yet at EOF), cleanup drains it."""
    client = PiClient()
    req_id = "req-drain"

    # 4 lines: 4th line is trailing unread output after agent_settled
    jsonl_lines = [
        json.dumps({"type": "response", "command": "prompt", "id": req_id, "success": True}).encode() + b"\n",
        json.dumps({
            "type": "message_end",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Net revenue retention is key."}]},
        }).encode() + b"\n",
        json.dumps({"type": "agent_settled"}).encode() + b"\n",
        json.dumps({"type": "metric", "data": {"tokens": 42}}).encode() + b"\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch("uuid.uuid4", return_value=MagicMock(hex="drain")), \
         patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await client.generate_response(prompt="Test retention", provider="ollama", model="qwen2.5:1.5b")

    assert result.text == "Net revenue retention is key."
    mock_proc.stdout.read.assert_called()
    mock_proc.stdin.close.assert_called_once()
    mock_proc._transport.close.assert_called_once()


@pytest.mark.asyncio
async def test_pi_cleanup_on_timeout():
    """Verify that a timeout triggers subprocess termination, stdin closure, and transport release."""
    client = PiClient()
    mock_proc = _build_mock_subprocess(hanging=True)

    with patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiTimeoutError):
            await client.generate_response(prompt="Hanging query", provider="ollama", model="qwen2.5:1.5b", timeout_seconds=1)

    mock_proc.terminate.assert_called()
    mock_proc.stdin.close.assert_called()
    mock_proc._transport.close.assert_called()


@pytest.mark.asyncio
async def test_pi_cleanup_on_subprocess_failure():
    """Verify that runtime errors (e.g., malformed JSONL or early termination) still clean up all resources."""
    client = PiClient()
    mock_proc = _build_mock_subprocess([b"NON_JSON_CRASH_DUMP\n"])

    with patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiOutputParseError):
            await client.generate_response(prompt="Crash query", provider="ollama", model="qwen2.5:1.5b")

    mock_proc.stdin.close.assert_called()
    mock_proc._transport.close.assert_called()


# ---------------------------------------------------------------------------
# Integration tests for AgentService & FastAPI respond endpoint
# ---------------------------------------------------------------------------

def test_prompt_construction_and_role_boundaries():
    """Verify that format_prompt enforces prototype disclaimer and bounds history."""
    msg1 = ChatMessage(id=uuid.uuid4(), session_id=uuid.uuid4(), role="user", content="First question")
    msg2 = ChatMessage(id=uuid.uuid4(), session_id=uuid.uuid4(), role="assistant", content="First answer")

    prompt = AgentService.format_prompt(history=[msg1, msg2], current_content="Second question")

    assert PROTOTYPE_SYSTEM_PROMPT in prompt
    assert "User: First question" in prompt
    assert "Assistant: First answer" in prompt
    assert "User: Second question" in prompt
    assert prompt.endswith("Assistant:")


def test_agent_endpoint_invalid_session_id(client: TestClient):
    """POST /api/sessions/{session_id}/respond returns 404 for nonexistent session."""
    non_existent_id = uuid.uuid4()
    response = client.post(
        f"/api/sessions/{non_existent_id}/respond",
        json={"content": "What is activation rate?"},
    )
    assert response.status_code == 404
    assert f"Session with ID '{non_existent_id}' not found." in response.json()["detail"]


def test_agent_endpoint_empty_content_validation(client: TestClient, db_session: Session):
    """POST /api/sessions/{session_id}/respond returns 422 for empty or whitespace content."""
    session = create_session(db=db_session, title="Validation Session")

    response = client.post(
        f"/api/sessions/{session.id}/respond",
        json={"content": "   "},
    )
    assert response.status_code == 422


def test_agent_endpoint_trusted_persistence(client: TestClient, db_session: Session):
    """Verify that a successful generation turn saves both user and assistant messages in PostgreSQL."""
    session = create_session(db=db_session, title="Persistence Session")

    mock_result = PiGenerationResult(
        text="Activation is when a user first experiences the core value proposition.",
        provider="ollama",
        model="qwen2.5:1.5b",
        raw_events=[],
    )

    with patch("backend.app.agent.pi_client.PiClient.generate_response", AsyncMock(return_value=mock_result)):
        response = client.post(
            f"/api/sessions/{session.id}/respond",
            json={"content": "How do you define activation?"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == str(session.id)
    assert data["provider"] == "ollama"
    assert data["model"] == "qwen2.5:1.5b"
    assert data["retried"] is False
    assert data["user_message"]["role"] == "user"
    assert data["user_message"]["content"] == "How do you define activation?"
    assert data["assistant_message"]["role"] == "assistant"
    assert "core value proposition" in data["assistant_message"]["content"]

    # Verify directly in database session
    messages, total = list_messages_by_session(db=db_session, session_id=session.id)
    assert total == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    assert messages[1].source_metadata["agent_framework"] == "pi_coding_agent"


def test_agent_endpoint_failure_preserves_user_message_without_fake_assistant(
    client: TestClient, db_session: Session
):
    """Verify that when Pi fails, the user message is saved but NO fabricated assistant message is created."""
    session = create_session(db=db_session, title="Failure Safety Session")

    with patch(
        "backend.app.agent.pi_client.PiClient.generate_response",
        AsyncMock(side_effect=PiTimeoutError("Pi process timed out")),
    ):
        response = client.post(
            f"/api/sessions/{session.id}/respond",
            json={"content": "Why is retention hard?"},
        )

    assert response.status_code == 504
    detail = response.json()["detail"]
    assert detail["error"] == "pi_timeout"
    assert detail["retryable"] is True

    # User message was preserved, but assistant message was NOT fabricated
    messages, total = list_messages_by_session(db=db_session, session_id=session.id)
    assert total == 1
    assert messages[0].role == "user"
    assert messages[0].content == "Why is retention hard?"


def test_agent_endpoint_idempotent_retry(client: TestClient, db_session: Session):
    """Verify that retrying after a failure reuses the existing user message without duplicating it."""
    session = create_session(db=db_session, title="Retry Session")

    # Turn 1: Fails due to runtime error
    with patch(
        "backend.app.agent.pi_client.PiClient.generate_response",
        AsyncMock(side_effect=PiAgentException("Temporary socket glitch")),
    ):
        resp1 = client.post(
            f"/api/sessions/{session.id}/respond",
            json={"content": "Explain product market fit."},
        )
    assert resp1.status_code == 502

    messages_after_fail, count1 = list_messages_by_session(db=db_session, session_id=session.id)
    assert count1 == 1

    # Turn 2: User retries the exact same prompt and it succeeds
    mock_result = PiGenerationResult(
        text="Product-market fit is when retention curves flatten and word-of-mouth accelerates.",
        provider="ollama",
        model="qwen2.5:1.5b",
        raw_events=[],
    )

    with patch("backend.app.agent.pi_client.PiClient.generate_response", AsyncMock(return_value=mock_result)):
        resp2 = client.post(
            f"/api/sessions/{session.id}/respond",
            json={"content": "Explain product market fit."},
        )

    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["retried"] is True

    # Total messages in DB should be exactly 2 (1 user, 1 assistant), NOT 3
    messages_after_retry, count2 = list_messages_by_session(db=db_session, session_id=session.id)
    assert count2 == 2
    assert messages_after_retry[0].role == "user"
    assert messages_after_retry[1].role == "assistant"


# ---------------------------------------------------------------------------
# Provider Error Detection & Safe Diagnostics Unit Tests (Mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pi_assistant_message_stop_reason_error_auth():
    """Verify that an assistant message with stopReason 'error' and auth failure raises PiAuthenticationError."""
    client = PiClient()
    req_id = "req-auth-err"

    jsonl_lines = [
        json.dumps({"type": "response", "command": "prompt", "id": req_id, "success": True}).encode() + b"\n",
        json.dumps({"type": "agent_start"}).encode() + b"\n",
        json.dumps({
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [],
                "stopReason": "error",
                "errorMessage": "API_KEY_INVALID: API key not valid. Please pass a valid API key.",
            },
        }).encode() + b"\n",
        json.dumps({"type": "agent_settled", "aborted": False}).encode() + b"\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch("uuid.uuid4", return_value=MagicMock(hex="auth-err")), \
         patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiAuthenticationError) as exc_info:
            await client.generate_response(
                prompt="Explain loops",
                provider="google",
                model="gemini-2.5-flash",
            )
        assert exc_info.value.provider == "google"
        assert exc_info.value.model == "gemini-2.5-flash"
        assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_pi_assistant_message_stop_reason_error_rate_limit():
    """Verify that an assistant message with stopReason 'error' and quota failure raises PiRateLimitError."""
    client = PiClient()
    req_id = "req-rate-err"

    jsonl_lines = [
        json.dumps({"type": "response", "command": "prompt", "id": req_id, "success": True}).encode() + b"\n",
        json.dumps({"type": "agent_start"}).encode() + b"\n",
        json.dumps({
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [],
                "stopReason": "error",
                "errorMessage": "RESOURCE_EXHAUSTED: Quota exceeded for quota metric 'Requests' and limit 'Requests per minute'",
            },
        }).encode() + b"\n",
        json.dumps({"type": "agent_settled", "aborted": False}).encode() + b"\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch("uuid.uuid4", return_value=MagicMock(hex="rate-err")), \
         patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiRateLimitError) as exc_info:
            await client.generate_response(
                prompt="Explain PMF",
                provider="google",
                model="gemini-2.5-flash",
            )
        assert exc_info.value.provider == "google"
        assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_pi_assistant_message_stop_reason_error_model_not_found():
    """Verify that an assistant message indicating unsupported or unknown model raises PiModelNotFoundError."""
    client = PiClient()
    req_id = "req-modelerr"

    jsonl_lines = [
        json.dumps({"type": "response", "command": "prompt", "id": req_id, "success": True}).encode() + b"\n",
        json.dumps({
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [],
                "stopReason": "error",
                "errorMessage": "models/gemini-unsupported is not found for API version v1beta",
            },
        }).encode() + b"\n",
        json.dumps({"type": "agent_settled", "aborted": False}).encode() + b"\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch("uuid.uuid4", return_value=MagicMock(hex="modelerr")), \
         patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiModelNotFoundError) as exc_info:
            await client.generate_response(
                prompt="Check model",
                provider="google",
                model="gemini-unsupported",
            )
        assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_pi_streaming_error_event():
    """Verify that a streaming error event from Pi RPC raises PiNetworkError."""
    client = PiClient()
    req_id = "req-streamer"

    jsonl_lines = [
        json.dumps({"type": "response", "command": "prompt", "id": req_id, "success": True}).encode() + b"\n",
        json.dumps({"type": "agent_start"}).encode() + b"\n",
        json.dumps({"type": "error", "error": "Google API connection refused: ETIMEDOUT"}).encode() + b"\n",
        json.dumps({"type": "agent_settled", "aborted": False}).encode() + b"\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch("uuid.uuid4", return_value=MagicMock(hex="streamer")), \
         patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiNetworkError) as exc_info:
            await client.generate_response(
                prompt="Check connection",
                provider="google",
                model="gemini-2.5-flash",
            )
        assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_pi_unsuccessful_rpc_command_response():
    """Verify that an unsuccessful RPC command response is detected and categorized correctly."""
    client = PiClient()
    req_id = "req-unsucces"

    jsonl_lines = [
        json.dumps({
            "type": "response",
            "command": "prompt",
            "id": req_id,
            "success": False,
            "error": "Model gemini-fake does not exist on provider google",
        }).encode() + b"\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch("uuid.uuid4", return_value=MagicMock(hex="unsucces")), \
         patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiModelNotFoundError) as exc_info:
            await client.generate_response(
                prompt="Invalid model test",
                provider="google",
                model="gemini-fake",
            )
        assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_pi_successful_google_gemini_response():
    """Verify successful Google Gemini generation returns the assistant text cleanly."""
    client = PiClient()
    req_id = "req-geminiok"

    jsonl_lines = [
        json.dumps({"type": "response", "command": "prompt", "id": req_id, "success": True}).encode() + b"\n",
        json.dumps({"type": "agent_start"}).encode() + b"\n",
        json.dumps({
            "type": "message_end",
            "message": {
                "role": "assistant",
                "stopReason": "stop",
                "content": [{"type": "text", "text": "Google Gemini 2.5 Flash response: Growth loops compound through retention."}],
            },
        }).encode() + b"\n",
        json.dumps({"type": "agent_settled", "aborted": False}).encode() + b"\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch("uuid.uuid4", return_value=MagicMock(hex="geminiok")), \
         patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await client.generate_response(
            prompt="Explain loops",
            provider="google",
            model="gemini-2.5-flash",
        )

    assert result.text == "Google Gemini 2.5 Flash response: Growth loops compound through retention."
    assert result.provider == "google"
    assert result.model == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_pi_genuine_successful_response_with_no_text():
    """Verify that a genuine successful completion that produced no text raises PiEmptyResponseError."""
    client = PiClient()
    req_id = "req-empty-ok"

    # Completed with stopReason 'stop' and no errors, but content is empty
    jsonl_lines = [
        json.dumps({"type": "response", "command": "prompt", "id": req_id, "success": True}).encode() + b"\n",
        json.dumps({"type": "agent_start"}).encode() + b"\n",
        json.dumps({
            "type": "message_end",
            "message": {
                "role": "assistant",
                "stopReason": "stop",
                "content": [],
            },
        }).encode() + b"\n",
        json.dumps({"type": "agent_settled", "aborted": False}).encode() + b"\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch("uuid.uuid4", return_value=MagicMock(hex="empty-ok")), \
         patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiEmptyResponseError) as exc_info:
            await client.generate_response(
                prompt="Empty reply test",
                provider="google",
                model="gemini-2.5-flash",
            )
        assert exc_info.value.provider == "google"
        assert exc_info.value.model == "gemini-2.5-flash"
        assert "empty assistant response" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_pi_child_process_failure_and_stderr():
    """Verify that child process stderr and nonzero exit code are captured as PiProviderError."""
    client = PiClient()
    mock_proc = _build_mock_subprocess(
        jsonl_lines=[],
        stderr_lines=[b"google provider error: 503 Backend service unavailable\n"],
    )
    mock_proc.returncode = 1

    with patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(PiProviderError) as exc_info:
            await client.generate_response(
                prompt="Stderr test",
                provider="google",
                model="gemini-2.5-flash",
            )
        assert "503 Backend service unavailable" in str(exc_info.value)


def test_pi_no_secret_exposure_in_sanitization_and_errors():
    """Verify that credentials (Gemini, OpenAI, Bearer tokens) are masked in error logs and exceptions."""
    raw_key = "AIzaSyFakeSecretKey1234567890abcdefXYZ"
    bearer_token = "Bearer fake_token_abc_123_xyz"

    sanitized = sanitize_secret_text(f"Connection failed for key {raw_key} with header {bearer_token}")
    assert raw_key not in sanitized
    assert "fake_token_abc_123_xyz" not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized
    assert "[REDACTED_TOKEN]" in sanitized

    # Verify exception message does not leak credentials when instantiated
    err = PiAuthenticationError(
        message=f"Google API rejected key {raw_key}",
        provider="google",
        model="gemini-2.5-flash",
    )
    assert raw_key not in str(err)
    assert "[REDACTED_API_KEY]" in str(err)


@pytest.mark.asyncio
async def test_pi_ollama_regression_compatibility():
    """Verify that local Ollama inference continues to function identically without regression."""
    client = PiClient()
    req_id = "req-ollamaok"

    jsonl_lines = [
        json.dumps({"type": "response", "command": "prompt", "id": req_id, "success": True}).encode() + b"\n",
        json.dumps({"type": "agent_start"}).encode() + b"\n",
        json.dumps({
            "type": "message_end",
            "message": {
                "role": "assistant",
                "stopReason": "stop",
                "content": [{"type": "text", "text": "Ollama local response on qwen2.5:1.5b."}],
            },
        }).encode() + b"\n",
        json.dumps({"type": "agent_settled", "aborted": False}).encode() + b"\n",
    ]
    mock_proc = _build_mock_subprocess(jsonl_lines)

    with patch("uuid.uuid4", return_value=MagicMock(hex="ollamaok")), \
         patch.object(client, "resolve_executable", return_value=["node", "cli.js"]), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await client.generate_response(
            prompt="Hello local",
            provider="ollama",
            model="qwen2.5:1.5b",
        )

    assert result.text == "Ollama local response on qwen2.5:1.5b."
    assert result.provider == "ollama"
    assert result.model == "qwen2.5:1.5b"

