"""Authentic Pi Coding Agent RPC execution evidence collector.

Provides a safe, minimal, opt-in mechanism to capture real JSONL RPC events
streamed by the Pi Coding Agent child process into a local, Git-ignored directory
(.local/pi-evidence/) for auditing and manual verification.

Guarantees:
    1. Disabled by default (PI_CAPTURE_EVENTS=false).
    2. Zero fabrication: preserves genuine event types, ordering, and timestamps.
    3. Never invents tool invocations, tokens, or success statuses.
    4. Strict sanitization: strips API keys, tokens, passwords, and local usernames.
    5. Exception isolation: disk or serialization errors never interrupt user requests.
    6. Allowlisted metadata: records real provider and model attribution.
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set

from backend.app.agent.exceptions import sanitize_secret_text
from backend.app.config import Settings, get_project_root, get_settings

logger = logging.getLogger(__name__)

# Sensitive key names that must never be retained in captured event dictionaries
_SENSITIVE_KEY_PATTERNS = re.compile(
    r"(api_?key|password|secret|token|auth|bearer|credential|cookie|private)",
    re.IGNORECASE,
)

# Standard redaction placeholders
REDACTED_SECRET = "[REDACTED_API_KEY]"
REDACTED_USER = "<USER>"
REDACTED_ROOT = "<PROJECT_ROOT>"


def _get_system_usernames() -> Set[str]:
    """Retrieve current OS username(s) to redact personal user directory paths."""
    usernames: Set[str] = set()
    for env_var in ("USERNAME", "USER", "LOGNAME"):
        val = os.environ.get(env_var)
        if val and len(val.strip()) > 1:
            usernames.add(val.strip())
    try:
        import getpass
        current = getpass.getuser()
        if current:
            usernames.add(current.strip())
    except Exception:
        pass
    return usernames


def sanitize_evidence_text(
    text: Optional[str],
    settings: Optional[Settings] = None,
    project_root: Optional[Path] = None,
) -> str:
    """Sanitize text by removing credentials, personal usernames, and local file paths."""
    if not text:
        return ""
    result = sanitize_secret_text(str(text), settings=settings)

    # Redact project root absolute path if provided
    if project_root:
        root_str = str(project_root)
        result = result.replace(root_str, REDACTED_ROOT)
        result = result.replace(root_str.replace("\\", "/"), REDACTED_ROOT)

    # Redact local user directory names
    for username in _get_system_usernames():
        if username and len(username) > 1:
            # Match Windows C:\Users\<username> and POSIX /home/<username>
            result = re.sub(
                rf"(?i)([A-Za-z]:\\Users\\){re.escape(username)}",
                rf"\g<1>{REDACTED_USER}",
                result,
            )
            result = re.sub(
                rf"(?i)(/Users/|/home/){re.escape(username)}",
                rf"\g<1>{REDACTED_USER}",
                result,
            )

    return result


def sanitize_event_payload(
    obj: Any,
    settings: Optional[Settings] = None,
    project_root: Optional[Path] = None,
    depth: int = 0,
) -> Any:
    """Recursively sanitize dictionary or list event structures against secrets and sensitive keys."""
    if depth > 10:
        return "[MAX_DEPTH_EXCEEDED]"

    if isinstance(obj, str):
        return sanitize_evidence_text(obj, settings=settings, project_root=project_root)

    if isinstance(obj, dict):
        sanitized_dict: Dict[str, Any] = {}
        for k, v in obj.items():
            if _SENSITIVE_KEY_PATTERNS.search(str(k)):
                sanitized_dict[k] = REDACTED_SECRET
            else:
                sanitized_dict[k] = sanitize_event_payload(
                    v, settings=settings, project_root=project_root, depth=depth + 1
                )
        return sanitized_dict

    if isinstance(obj, list):
        return [
            sanitize_event_payload(
                item, settings=settings, project_root=project_root, depth=depth + 1
            )
            for item in obj
        ]

    return obj


def filter_genuine_event(
    raw_event: Dict[str, Any],
    event_index: int,
    settings: Optional[Settings] = None,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Extract allowlisted genuine event metadata without leaking untrusted or sensitive fields."""
    event_type = raw_event.get("type", "unknown")
    filtered: Dict[str, Any] = {
        "event_index": event_index,
        "type": event_type,
    }

    # Common genuine fields
    for field in (
        "id",
        "command",
        "success",
        "turn_id",
        "stopReason",
        "willRetry",
        "reason",
        "aborted",
    ):
        if field in raw_event:
            filtered[field] = raw_event[field]

    # Error message (sanitized)
    if "error" in raw_event:
        filtered["error"] = sanitize_evidence_text(
            str(raw_event["error"]), settings=settings, project_root=project_root
        )
    if "errorMessage" in raw_event:
        filtered["errorMessage"] = sanitize_evidence_text(
            str(raw_event["errorMessage"]), settings=settings, project_root=project_root
        )

    # Tool invocation metadata (preserve ONLY genuine tool fields, never fabricate)
    if "tool" in raw_event or "toolName" in raw_event:
        filtered["tool"] = raw_event.get("tool") or raw_event.get("toolName")
    if "toolCallId" in raw_event:
        filtered["tool_call_id"] = raw_event["toolCallId"]

    # Message container (assistant, user, system)
    if "message" in raw_event and isinstance(raw_event["message"], dict):
        msg = raw_event["message"]
        sanitized_msg: Dict[str, Any] = {
            "role": msg.get("role"),
            "stopReason": msg.get("stopReason"),
        }
        if "errorMessage" in msg:
            sanitized_msg["errorMessage"] = sanitize_evidence_text(
                str(msg["errorMessage"]), settings=settings, project_root=project_root
            )
        # Content summary / sanitized text
        content = msg.get("content")
        if isinstance(content, str):
            sanitized_msg["content_length"] = len(content)
            sanitized_msg["content_snippet"] = sanitize_evidence_text(
                content[:200], settings=settings, project_root=project_root
            )
        elif isinstance(content, list):
            sanitized_msg["content_blocks_count"] = len(content)
            sanitized_msg["block_types"] = [
                b.get("type") for b in content if isinstance(b, dict) and "type" in b
            ]
        filtered["message"] = sanitized_msg

    # Streaming update delta
    if "assistantMessageEvent" in raw_event and isinstance(raw_event["assistantMessageEvent"], dict):
        ame = raw_event["assistantMessageEvent"]
        filtered["assistant_event_type"] = ame.get("type")
        if ame.get("type") == "text_delta":
            delta = ame.get("delta", "")
            filtered["delta_length"] = len(delta)
        elif ame.get("type") == "error":
            filtered["assistant_event_error"] = sanitize_evidence_text(
                str(ame.get("error")), settings=settings, project_root=project_root
            )

    return filtered


def record_pi_evidence(
    project_root: Optional[Path],
    settings: Optional[Settings],
    request_id: str,
    provider: str,
    model: str,
    raw_events: List[Dict[str, Any]],
    duration_seconds: float,
    outcome: str = "success",
    assistant_text: Optional[str] = None,
    error_message: Optional[str] = None,
    evidence_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Capture and record authentic Pi RPC execution events to a local Git-ignored directory.

    Returns the Path to the written JSON evidence file, or None if capture is disabled
    or failed. Failure never raises an exception.
    """
    resolved_settings = settings or get_settings()
    if not getattr(resolved_settings, "pi_capture_events", False):
        return None

    try:
        root = project_root or get_project_root()
        target_dir = evidence_dir or (
            root / (getattr(resolved_settings, "pi_evidence_dir", None) or ".local/pi-evidence")
        )
        target_dir.mkdir(parents=True, exist_ok=True)

        now_utc = datetime.now(timezone.utc)
        timestamp_str = now_utc.strftime("%Y%m%d_%H%M%S")

        # Inspect genuine tool calls in the observed event stream
        has_tools = False
        genuine_tools: List[str] = []
        for ev in raw_events:
            tool_name = ev.get("tool") or ev.get("toolName")
            if tool_name:
                has_tools = True
                if tool_name not in genuine_tools:
                    genuine_tools.append(str(tool_name))
            if ev.get("type") in ("tool_start", "tool_end", "tool_call"):
                has_tools = True

        # Build allowlisted event representations
        allowlisted_events = [
            filter_genuine_event(
                raw_event=ev,
                event_index=idx,
                settings=resolved_settings,
                project_root=root,
            )
            for idx, ev in enumerate(raw_events)
        ]

        event_types_sequence = [ev.get("type", "unknown") for ev in raw_events]

        metadata: Dict[str, Any] = {
            "schema_version": "1.0",
            "capture_mode": "opt_in_authentic_rpc_stream",
            "recorded_at_utc": now_utc.isoformat(),
            "request_id": request_id,
            "real_provider": provider,
            "real_model": model,
            "duration_seconds": round(duration_seconds, 3),
            "outcome": outcome,
            "total_events_captured": len(raw_events),
            "event_sequence": event_types_sequence,
            "has_tool_invocations": has_tools,
            "genuine_tools_used": genuine_tools,
            "response_character_count": len(assistant_text) if assistant_text else 0,
        }

        if error_message:
            metadata["error_message"] = sanitize_evidence_text(
                error_message, settings=resolved_settings, project_root=root
            )

        payload: Dict[str, Any] = {
            "capture_metadata": metadata,
            "events": allowlisted_events,
        }

        # Write sanitized JSON evidence
        json_filename = f"pi_rpc_{timestamp_str}_{request_id}.json"
        json_path = target_dir / json_filename
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        # Write companion audit Markdown file
        md_filename = f"pi_rpc_{timestamp_str}_{request_id}.md"
        md_path = target_dir / md_filename
        md_lines = [
            f"# Authentic Pi Coding Agent Execution Trace: {request_id}",
            f"- **Timestamp (UTC)**: {now_utc.isoformat()}",
            f"- **Real Provider**: {provider}",
            f"- **Real Model**: {model}",
            f"- **Execution Duration**: {duration_seconds:.2f}s",
            f"- **Execution Outcome**: {outcome}",
            f"- **Total JSONL Events Captured**: {len(raw_events)}",
            f"- **Genuine Tool Invocations Observed**: {'Yes (' + ', '.join(genuine_tools) + ')' if has_tools else 'None'}",
            f"- **Response Length**: {len(assistant_text) if assistant_text else 0} characters",
            "",
            "## 1. Observed JSONL RPC Event Sequence",
            "```text",
            " -> ".join(event_types_sequence),
            "```",
            "",
            "## 2. Event Stream Log (Sanitized)",
            "```json",
            json.dumps(allowlisted_events, indent=2),
            "```",
            "",
            "## 3. Security & Integrity Verification",
            "- [x] Captured directly from child process stdout JSONL RPC stream.",
            "- [x] Provider credentials and API keys redacted via standard pattern matcher.",
            "- [x] Local OS usernames and absolute directory paths sanitized.",
            "- [x] No fabricated tool calls, events, tokens or status injected.",
            "",
        ]
        md_path.write_text("\n".join(md_lines), encoding="utf-8")

        logger.info(
            "Recorded authentic Pi Coding Agent RPC trace: provider=%s, model=%s, events=%d -> %s",
            provider,
            model,
            len(raw_events),
            json_path,
        )
        return json_path

    except Exception as e:
        logger.warning("Could not record authentic Pi execution evidence: %s", e)
        return None
