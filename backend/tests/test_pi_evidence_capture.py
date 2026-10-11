"""Unit tests for the authentic Pi Coding Agent RPC execution evidence collector.

Covers:
    1. Disabled-by-default capture (PI_CAPTURE_EVENTS=false).
    2. Real event order and type preservation.
    3. Sensitive data exclusion (API keys, tokens, passwords, local usernames).
    4. Capture failure isolation (disk errors never crash requests).
    5. Real provider and model attribution.
    6. Non-fabrication of tool calls.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.app.agent.evidence_collector import (
    filter_genuine_event,
    record_pi_evidence,
    sanitize_evidence_text,
    sanitize_event_payload,
)
from backend.app.config import Settings


# ---------------------------------------------------------------------------
# 1. Disabled-by-default capture
# ---------------------------------------------------------------------------

def test_evidence_capture_disabled_by_default(tmp_path: Path):
    """Verify that evidence capture is disabled by default and writes zero files."""
    settings = Settings()
    assert settings.pi_capture_events is False

    raw_events = [
        {"type": "agent_start"},
        {"type": "turn_start", "turn_id": 1},
        {"type": "agent_settled"},
    ]

    result = record_pi_evidence(
        project_root=tmp_path,
        settings=settings,
        request_id="req-test-disabled",
        provider="ollama",
        model="qwen2.5:1.5b",
        raw_events=raw_events,
        duration_seconds=1.25,
        evidence_dir=tmp_path / "evidence",
    )

    assert result is None
    # No files or directories created
    assert not (tmp_path / "evidence").exists()


# ---------------------------------------------------------------------------
# 2. Real event order and type preservation
# ---------------------------------------------------------------------------

def test_evidence_capture_real_event_order_preservation(tmp_path: Path):
    """Verify that genuine event types and their exact stream ordering are preserved."""
    settings = Settings(pi_capture_events=True)
    evidence_dir = tmp_path / "evidence"

    raw_events = [
        {"type": "response", "command": "prompt", "id": "req-seq-001", "success": True},
        {"type": "agent_start"},
        {"type": "turn_start", "turn_id": 1},
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Retention curves"}},
        {"type": "message_end", "message": {"role": "assistant", "content": "Retention curves are foundational.", "stopReason": "stop"}},
        {"type": "turn_end", "turn_id": 1},
        {"type": "agent_end", "willRetry": False},
        {"type": "agent_settled"},
    ]

    written_path = record_pi_evidence(
        project_root=tmp_path,
        settings=settings,
        request_id="req-seq-001",
        provider="google",
        model="gemini-2.5-flash",
        raw_events=raw_events,
        duration_seconds=2.84,
        assistant_text="Retention curves are foundational.",
        evidence_dir=evidence_dir,
    )

    assert written_path is not None
    assert written_path.exists()

    data = json.loads(written_path.read_text(encoding="utf-8"))
    assert data["capture_metadata"]["total_events_captured"] == 8

    # Verify exact sequence preservation
    expected_types = [
        "response",
        "agent_start",
        "turn_start",
        "message_update",
        "message_end",
        "turn_end",
        "agent_end",
        "agent_settled",
    ]
    assert data["capture_metadata"]["event_sequence"] == expected_types

    # Verify event index numbering is strictly sequential (0 to 7)
    captured_indices = [ev["event_index"] for ev in data["events"]]
    assert captured_indices == list(range(8))

    # Verify companion markdown report exists
    md_path = written_path.with_suffix(".md")
    assert md_path.exists()
    md_content = md_path.read_text(encoding="utf-8")
    assert "Authentic Pi Coding Agent Execution Trace" in md_content
    assert "req-seq-001" in md_content


# ---------------------------------------------------------------------------
# 3. Sensitive data exclusion
# ---------------------------------------------------------------------------

def test_evidence_capture_sensitive_data_exclusion(tmp_path: Path):
    """Verify that real credentials, bearer tokens, and user paths are redacted."""
    test_gemini_key = "AIzaSyD-RealSecretKey998877665544"
    test_openai_key = "sk-proj-RealOpenAIKey1234567890abcdef"
    test_bearer_token = "Bearer secret_bearer_token_xyz"

    settings = Settings(
        pi_capture_events=True,
        gemini_api_key=test_gemini_key,
        openai_api_key=test_openai_key,
    )
    evidence_dir = tmp_path / "evidence"

    # Event containing sensitive data in text and metadata
    raw_events = [
        {
            "type": "error",
            "error": f"Failed with {test_gemini_key} at C:\\Users\\Happy\\AppData\\Local\\temp",
        },
        {
            "type": "turn_start",
            "turn_id": 1,
            "apiKey": "nested_secret_to_redact",
            "authorization": test_bearer_token,
        },
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": f"Here is output with {test_openai_key}",
            },
        },
    ]

    written_path = record_pi_evidence(
        project_root=tmp_path,
        settings=settings,
        request_id="req-leak-test",
        provider="google",
        model="gemini-2.5-flash",
        raw_events=raw_events,
        duration_seconds=0.5,
        evidence_dir=evidence_dir,
    )

    assert written_path is not None
    json_text = written_path.read_text(encoding="utf-8")

    # Assert raw secrets are absent
    assert test_gemini_key not in json_text
    assert test_openai_key not in json_text
    assert "secret_bearer_token_xyz" not in json_text
    assert "nested_secret_to_redact" not in json_text

    # Assert standard redaction tokens are present
    assert "[REDACTED_API_KEY]" in json_text or "Bearer [REDACTED_TOKEN]" in json_text


def test_sanitize_evidence_text_user_path_redaction():
    """Verify personal Windows and POSIX username paths are masked with <USER>."""
    with patch("backend.app.agent.evidence_collector._get_system_usernames", return_value={"SpecialUser"}):
        sanitized = sanitize_evidence_text(r"C:\Users\SpecialUser\OogwayLabs\project\.env")
        assert "SpecialUser" not in sanitized
        assert r"C:\Users\<USER>\OogwayLabs\project\.env" in sanitized

        sanitized_posix = sanitize_evidence_text("/home/SpecialUser/project")
        assert "SpecialUser" not in sanitized_posix
        assert "/home/<USER>/project" in sanitized_posix


# ---------------------------------------------------------------------------
# 4. Capture failure isolation
# ---------------------------------------------------------------------------

def test_evidence_capture_failure_isolation(tmp_path: Path):
    """Verify that filesystem write failures are gracefully handled without raising."""
    settings = Settings(pi_capture_events=True)

    raw_events = [{"type": "agent_start"}]

    # Mock Path.write_text to raise an OSError (e.g. disk full or read-only volume)
    with patch.object(Path, "write_text", side_effect=OSError("Read-only filesystem")):
        result = record_pi_evidence(
            project_root=tmp_path,
            settings=settings,
            request_id="req-err-isolation",
            provider="ollama",
            model="qwen2.5:1.5b",
            raw_events=raw_events,
            duration_seconds=1.0,
            evidence_dir=tmp_path / "evidence",
        )
        # Should gracefully return None without raising
        assert result is None


# ---------------------------------------------------------------------------
# 5. Real provider and model attribution
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "prov,mod",
    [
        ("google", "gemini-2.5-flash"),
        ("ollama", "qwen2.5:1.5b"),
        ("openai", "gpt-4o-mini"),
    ],
)
def test_evidence_capture_provider_model_attribution(tmp_path: Path, prov: str, mod: str):
    """Verify real provider and model attribution are recorded faithfully."""
    settings = Settings(pi_capture_events=True)

    written_path = record_pi_evidence(
        project_root=tmp_path,
        settings=settings,
        request_id=f"req-{prov}-attr",
        provider=prov,
        model=mod,
        raw_events=[{"type": "agent_settled"}],
        duration_seconds=1.5,
        evidence_dir=tmp_path / "evidence",
    )

    assert written_path is not None
    data = json.loads(written_path.read_text(encoding="utf-8"))
    meta = data["capture_metadata"]

    assert meta["real_provider"] == prov
    assert meta["real_model"] == mod


# ---------------------------------------------------------------------------
# 6. Non-fabrication of tool calls
# ---------------------------------------------------------------------------

def test_evidence_capture_strictly_reflects_tool_invocations(tmp_path: Path):
    """Verify that tool invocations are never fabricated when no tools were used."""
    settings = Settings(pi_capture_events=True)

    # 1. Execution without tools
    no_tool_events = [
        {"type": "agent_start"},
        {"type": "turn_start", "turn_id": 1},
        {"type": "turn_end", "turn_id": 1},
        {"type": "agent_settled"},
    ]

    p1 = record_pi_evidence(
        project_root=tmp_path,
        settings=settings,
        request_id="req-no-tools",
        provider="ollama",
        model="qwen2.5:1.5b",
        raw_events=no_tool_events,
        duration_seconds=1.0,
        evidence_dir=tmp_path / "evidence",
    )
    d1 = json.loads(p1.read_text(encoding="utf-8"))
    assert d1["capture_metadata"]["has_tool_invocations"] is False
    assert d1["capture_metadata"]["genuine_tools_used"] == []

    # 2. Execution with a genuine tool
    tool_events = [
        {"type": "agent_start"},
        {"type": "tool_start", "tool": "search_podcast_chunks", "toolCallId": "call_1"},
        {"type": "tool_end", "tool": "search_podcast_chunks", "toolCallId": "call_1"},
        {"type": "agent_settled"},
    ]

    p2 = record_pi_evidence(
        project_root=tmp_path,
        settings=settings,
        request_id="req-with-tools",
        provider="ollama",
        model="qwen2.5:1.5b",
        raw_events=tool_events,
        duration_seconds=1.0,
        evidence_dir=tmp_path / "evidence",
    )
    d2 = json.loads(p2.read_text(encoding="utf-8"))
    assert d2["capture_metadata"]["has_tool_invocations"] is True
    assert d2["capture_metadata"]["genuine_tools_used"] == ["search_podcast_chunks"]
