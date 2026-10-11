"""Subprocess client for communicating with the Pi Coding Agent runtime via JSONL RPC."""

import asyncio
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple
import uuid

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
    sanitize_secret_text,
)
from backend.app.config import Settings, get_project_root, get_settings

logger = logging.getLogger(__name__)



@dataclass
class PiGenerationResult:
    """Result returned by a completed Pi Coding Agent generation."""

    text: str
    provider: str
    model: str
    raw_events: List[Dict[str, Any]]


class PiClient:
    """Manages execution and JSONL RPC communication with the local Pi Coding Agent."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.project_root = get_project_root()
        self.agent_runtime_dir = self.project_root / "agent_runtime"
        self.local_pi_dir = (
            Path(self.settings.pi_agent_dir)
            if self.settings.pi_agent_dir
            else self.project_root / ".local" / "pi-agent"
        )

    def resolve_executable(self) -> List[str]:
        """Resolve the command and executable arguments to invoke Pi on Windows or POSIX.

        Resolution strategy:
            1. Explicit settings.pi_agent_executable if configured.
            2. Local agent_runtime/node_modules/.bin/pi.cmd (Windows) or .bin/pi (POSIX).
            3. Local agent_runtime/node_modules/@earendil-works/pi-coding-agent CLI script via node.
            4. System PATH search for pi.cmd or pi.
            5. Raises PiNotInstalledError with actionable remediation instructions.
        """
        # 1. Explicit override
        if self.settings.pi_agent_executable:
            exec_path = Path(self.settings.pi_agent_executable)
            if exec_path.exists():
                return [str(exec_path)]
            if shutil.which(self.settings.pi_agent_executable):
                return [self.settings.pi_agent_executable]

        # 2. Local node_modules/.bin
        is_windows = os.name == "nt"
        bin_name = "pi.cmd" if is_windows else "pi"
        local_bin = self.agent_runtime_dir / "node_modules" / ".bin" / bin_name
        if local_bin.exists():
            return [str(local_bin)]

        # 3. Direct Node.js invocation of package CLI entrypoint (avoids Windows cmd shell wrappers)
        pkg_cli = (
            self.agent_runtime_dir
            / "node_modules"
            / "@earendil-works"
            / "pi-coding-agent"
            / "dist"
            / "cli.js"
        )
        if pkg_cli.exists():
            node_bin = shutil.which("node") or "node"
            return [node_bin, str(pkg_cli)]

        # 4. System PATH search
        path_bin = shutil.which("pi.cmd" if is_windows else "pi")
        if path_bin:
            return [path_bin]

        # 5. Not found — raise structured error with remediation steps
        raise PiNotInstalledError(
            "Pi Coding Agent (@earendil-works/pi-coding-agent) could not be located.\n"
            "Remediation steps:\n"
            f"  1. Open a terminal in the project root: {self.project_root}\n"
            "  2. Navigate to agent_runtime and install dependencies:\n"
            "       cd agent_runtime\n"
            "       npm install\n"
            "       cd ..\n"
            "  3. Verify installation: node_modules/@earendil-works/pi-coding-agent"
        )

    def ensure_local_models_config(self) -> Path:
        """Ensure the .local/pi-agent/models.json file exists for Ollama provider configuration.

        If missing or if the configured Ollama base URL differs (e.g. host.docker.internal
        inside Docker containers), syncs models.json with the project settings.
        """
        self.local_pi_dir.mkdir(parents=True, exist_ok=True)
        models_file = self.local_pi_dir / "models.json"

        target_base_url = f"{self.settings.ollama_base_url.rstrip('/')}/v1"
        needs_write = False
        config_data = {}

        if models_file.exists():
            try:
                config_data = json.loads(models_file.read_text(encoding="utf-8"))
                current_base_url = (
                    config_data.get("providers", {})
                    .get("ollama", {})
                    .get("baseUrl")
                )
                if current_base_url != target_base_url:
                    config_data.setdefault("providers", {}).setdefault("ollama", {})["baseUrl"] = target_base_url
                    needs_write = True
            except Exception:
                needs_write = True
        else:
            needs_write = True

        if needs_write:
            if not config_data or "providers" not in config_data:
                config_data = {
                    "providers": {
                        "ollama": {
                            "baseUrl": target_base_url,
                            "api": "openai-completions",
                            "apiKey": "ollama",
                            "models": [{"id": self.settings.ollama_model}],
                        }
                    }
                }
            try:
                models_file.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
                logger.info("Synchronized Pi models.json Ollama baseUrl to %s", target_base_url)
            except Exception as e:
                logger.warning("Could not write Pi models.json: %s", e)

        return models_file

    def validate_provider_model(
        self, provider: Optional[str] = None, model: Optional[str] = None
    ) -> Tuple[str, str]:
        """Validate LLM provider credentials and return the normalized (provider, model) tuple."""
        prov = (provider or self.settings.llm_provider or "ollama").strip().lower()

        if prov in ("google", "gemini"):
            if not self.settings.gemini_api_key or not self.settings.gemini_api_key.strip():
                raise PiConfigurationError(
                    "Cloud provider 'google' (Google Gemini) is selected, but GEMINI_API_KEY is not configured in .env."
                )
            target_model = model or self.settings.gemini_model or "gemini-2.5-flash"
            return "google", target_model

        if prov == "ollama":
            target_model = model or self.settings.ollama_model or "qwen2.5:1.5b"
            return "ollama", target_model

        # Backward compatibility for historical records
        if prov == "openai":
            if not getattr(self.settings, "openai_api_key", None) or not str(self.settings.openai_api_key).strip():
                raise PiConfigurationError(
                    "Cloud provider 'openai' is selected, but OPENAI_API_KEY is not configured in .env."
                )
            return "openai", model or getattr(self.settings, "openai_model", "gpt-4o-mini")

        if prov == "anthropic":
            if not getattr(self.settings, "anthropic_api_key", None) or not str(self.settings.anthropic_api_key).strip():
                raise PiConfigurationError(
                    "Cloud provider 'anthropic' is selected, but ANTHROPIC_API_KEY is not configured in .env."
                )
            return "anthropic", model or getattr(self.settings, "anthropic_model", "claude-3-5-sonnet-20241022")

        raise PiConfigurationError(
            f"Unsupported LLM provider '{provider}'. Supported providers: 'ollama', 'google'."
        )

    def validate_provider_configuration(
        self, provider: Optional[str] = None, model: Optional[str] = None
    ) -> Tuple[str, str]:
        """Validate LLM provider credentials and return the normalized (provider, model) tuple (alias)."""
        return self.validate_provider_model(provider, model)

    def build_command_args(self, provider: str, model: str) -> List[str]:
        """Build the full subprocess argument list enforcing zero dangerous tools."""
        base_cmd = self.resolve_executable()
        args = [
            *base_cmd,
            "--mode",
            "rpc",
            "--no-session",
            "--no-tools",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-mcp",
            "--no-context-files",
            "--provider",
            provider,
            "--model",
            model,
        ]
        return args

    def build_subprocess_env(self) -> Dict[str, str]:
        """Construct a safe environment dictionary for the Pi subprocess."""
        env = os.environ.copy()
        # Set PI_CODING_AGENT_DIR so Pi discovers .local/pi-agent/models.json
        env["PI_CODING_AGENT_DIR"] = str(self.local_pi_dir)

        # Inject configured Google Gemini key into subprocess env
        if self.settings.gemini_api_key and self.settings.gemini_api_key.strip():
            cleaned_gemini_key = self.settings.gemini_api_key.strip()
            env["GEMINI_API_KEY"] = cleaned_gemini_key
            env["GOOGLE_API_KEY"] = cleaned_gemini_key

        # Inject legacy keys if configured
        if getattr(self.settings, "openai_api_key", None):
            env["OPENAI_API_KEY"] = self.settings.openai_api_key
        if getattr(self.settings, "anthropic_api_key", None):
            env["ANTHROPIC_API_KEY"] = self.settings.anthropic_api_key

        return env

    @classmethod
    def _detect_provider_error(
        cls,
        events: List[Dict[str, Any]],
        stderr_output: List[str],
        provider: str,
        model: str,
    ) -> Optional[PiAgentException]:
        """Inspect captured JSONL events and stderr to detect, classify, and sanitize upstream provider errors.

        Guarantees:
            1. Identifies terminal assistant messages with stopReason == 'error' or 'aborted'.
            2. Detects explicit errorMessage fields on messages or stream events.
            3. Catches auto_retry_end failures and unsuccessful responses.
            4. Inspects child-process stderr for upstream connection or SDK failures.
            5. Sanitizes all credentials before constructing structured domain exceptions.
        """
        raw_error_message: Optional[str] = None
        stop_reason: Optional[str] = None
        is_prompt_command_failure: bool = False

        # 1. Inspect events in reverse order to identify the authoritative final error
        for ev in reversed(events):
            ev_type = ev.get("type")

            # Check message_end for role == 'assistant'
            if ev_type == "message_end":
                msg = ev.get("message", {})
                if msg.get("role") == "assistant":
                    sr = msg.get("stopReason")
                    em = msg.get("errorMessage")
                    if sr in ("error", "aborted") or em:
                        stop_reason = sr or "error"
                        raw_error_message = em or f"Provider stopped with reason: {sr}"
                        break

            # Check agent_end messages array
            if ev_type == "agent_end":
                for msg in reversed(ev.get("messages", [])):
                    if msg.get("role") == "assistant":
                        sr = msg.get("stopReason")
                        em = msg.get("errorMessage")
                        if sr in ("error", "aborted") or em:
                            stop_reason = sr or "error"
                            raw_error_message = em or f"Provider stopped with reason: {sr}"
                            break
                if raw_error_message:
                    break

            # Check turn_end
            if ev_type == "turn_end":
                msg = ev.get("message", {})
                if msg.get("role") == "assistant":
                    sr = msg.get("stopReason")
                    em = msg.get("errorMessage")
                    if sr in ("error", "aborted") or em:
                        stop_reason = sr or "error"
                        raw_error_message = em or f"Provider stopped with reason: {sr}"
                        break

            # Check auto_retry_end failure
            if ev_type == "auto_retry_end" and ev.get("success") is False:
                raw_error_message = ev.get("finalError") or ev.get("errorMessage") or "Auto-retry failed"
                stop_reason = "error"
                break

            # Check streaming error
            if ev_type == "message_update":
                update = ev.get("assistantMessageEvent", {})
                if update.get("type") == "error":
                    err_payload = update.get("error")
                    if isinstance(err_payload, dict):
                        raw_error_message = err_payload.get("errorMessage") or str(err_payload)
                    elif isinstance(err_payload, str):
                        raw_error_message = err_payload
                    stop_reason = update.get("reason") or "error"
                    break

            # Check top-level error or extension_error
            if ev_type in ("error", "extension_error"):
                raw_error_message = ev.get("error") or ev.get("message")
                stop_reason = "error"
                break

            # Check prompt command response failure
            if ev_type == "response" and ev.get("command") == "prompt" and not ev.get("success"):
                raw_error_message = ev.get("error") or ev.get("data", {}).get("message") or "Prompt rejected by Pi"
                stop_reason = "error"
                is_prompt_command_failure = True
                break

        # 2. Check if agent_settled was aborted
        if not raw_error_message:
            for ev in events:
                if ev.get("type") == "agent_settled" and ev.get("aborted") is True:
                    stop_reason = "aborted"
                    raw_error_message = "Agent execution was aborted"
                    break

        # 3. Check stderr if no error message was captured from JSONL stdout
        if not raw_error_message and stderr_output:
            for line in reversed(stderr_output):
                line_lower = line.lower()
                if any(kw in line_lower for kw in ("error:", "exception:", "failed", "fatal", "econnrefused", "invalid api key", "unauthorized", "503", "unavailable", "service unavailable")):
                    raw_error_message = line
                    stop_reason = "error"
                    break

        if not raw_error_message and not stop_reason:
            return None

        # Sanitize any accidental secrets in the raw message
        sanitized_details = sanitize_secret_text(raw_error_message or f"Stop reason: {stop_reason}")
        err_lower = sanitized_details.lower()

        # Classify the error into structured domain exceptions
        if any(kw in err_lower for kw in ("api key not valid", "invalid api key", "api_key_invalid", "401", "unauthorized", "403", "forbidden", "permission denied", "permission_denied", "no api key")):
            return PiAuthenticationError(
                message=(
                    f"Authentication failed for {provider} model '{model}'. "
                    "Verify that the API key is configured correctly and has valid access."
                ),
                provider=provider,
                model=model,
                details=sanitized_details,
            )

        if any(kw in err_lower for kw in ("429", "quota", "rate limit", "ratelimit", "resource_exhausted", "resource exhausted", "too many requests")):
            return PiRateLimitError(
                message=(
                    f"Rate limit or quota exceeded for {provider} model '{model}'. "
                    "Please wait before retrying (free-tier accounts have request limits)."
                ),
                provider=provider,
                model=model,
                details=sanitized_details,
            )

        if any(kw in err_lower for kw in ("404", "model not found", "not found", "is not supported", "invalid model", "model_not_found", "unknown model", "does not exist", "no such model", "unsupported model")):
            return PiModelNotFoundError(
                message=(
                    f"Model '{model}' is not supported or was not found on provider '{provider}'. "
                    "Please check your configured model identifier."
                ),
                provider=provider,
                model=model,
                details=sanitized_details,
            )

        if any(kw in err_lower for kw in ("econnrefused", "fetch failed", "enotfound", "connection reset", "network error", "socket hang up", "etimedout", "dns")):
            return PiNetworkError(
                message=(
                    f"Network connection to {provider} failed. "
                    "Please verify internet connectivity and provider host access."
                ),
                provider=provider,
                model=model,
                details=sanitized_details,
            )

        if stop_reason == "aborted" or "aborted" in err_lower:
            return PiProcessTerminatedError(
                message=f"Generation run with {provider} ({model}) was aborted.",
                details=sanitized_details,
            )

        # Distinguish command-level prompt rejection from assistant generation provider errors
        if is_prompt_command_failure:
            return PiPromptRejectedError(
                f"Pi rejected prompt: {sanitized_details}",
            )

        return PiProviderError(
            message=f"Upstream provider error from {provider} ({model}): {sanitized_details}",
            provider=provider,
            model=model,
            details=sanitized_details,
        )

    @staticmethod
    def _extract_assistant_text(events: List[Dict[str, Any]]) -> str:
        """Extract the complete assistant text from the captured JSONL event sequence."""
        # 1. First preference: check 'message_end' for role == 'assistant'
        for ev in reversed(events):
            if ev.get("type") == "message_end":
                msg = ev.get("message", {})
                if msg.get("role") == "assistant":
                    content = msg.get("content")
                    if isinstance(content, str):
                        return content.strip()
                    if isinstance(content, list):
                        parts = [
                            b.get("text", "")
                            for b in content
                            if isinstance(b, dict) and b.get("type") == "text"
                        ]
                        text = "".join(parts).strip()
                        if text:
                            return text

        # 2. Second preference: check 'agent_end' messages
        for ev in reversed(events):
            if ev.get("type") == "agent_end":
                msgs = ev.get("messages", [])
                for msg in reversed(msgs):
                    if msg.get("role") == "assistant":
                        content = msg.get("content")
                        if isinstance(content, str) and content.strip():
                            return content.strip()
                        if isinstance(content, list):
                            parts = [
                                b.get("text", "")
                                for b in content
                                if isinstance(b, dict) and b.get("type") == "text"
                            ]
                            text = "".join(parts).strip()
                            if text:
                                return text

        # 3. Third preference: check 'turn_end' message
        for ev in reversed(events):
            if ev.get("type") == "turn_end":
                msg = ev.get("message", {})
                if msg.get("role") == "assistant":
                    content = msg.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip()
                    if isinstance(content, list):
                        parts = [
                            b.get("text", "")
                            for b in content
                            if isinstance(b, dict) and b.get("type") == "text"
                        ]
                        text = "".join(parts).strip()
                        if text:
                            return text

        # 4. Fourth preference: assemble from 'text_delta' updates
        deltas = []
        for ev in events:
            if ev.get("type") == "message_update":
                update = ev.get("assistantMessageEvent", {})
                if update.get("type") == "text_delta":
                    deltas.append(update.get("delta", ""))
        assembled = "".join(deltas).strip()
        if assembled:
            return assembled

        return ""

    async def generate_response(
        self,
        prompt: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> PiGenerationResult:
        """Execute a genuine generation turn through the Pi Coding Agent RPC interface.

        Workflow:
            1. Validate provider and model configuration.
            2. Ensure .local/pi-agent/models.json exists.
            3. Spawn Pi subprocess in RPC mode with tools disabled.
            4. Send JSONL prompt command via stdin.
            5. Stream and parse JSONL events from stdout.
            6. Verify prompt acceptance (success: true).
            7. Await the 'agent_settled' event (settled completion).
            8. Extract generated assistant text and return structured result.
            9. Enforce strict timeout and process lifecycle cleanup.
        """
        validated_provider, validated_model = self.validate_provider_model(
            provider, model
        )

        self.ensure_local_models_config()
        cmd_args = self.build_command_args(validated_provider, validated_model)
        proc_env = self.build_subprocess_env()
        timeout = timeout_seconds or self.settings.pi_agent_timeout_seconds

        req_id = f"req-{uuid.uuid4().hex[:8]}"
        prompt_command = {
            "id": req_id,
            "type": "prompt",
            "message": prompt,
        }

        logger.info(
            "Launching Pi Coding Agent subprocess: provider=%s, model=%s, req_id=%s",
            validated_provider,
            validated_model,
            req_id,
        )

        start_time = asyncio.get_event_loop().time()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.project_root),
                env=proc_env,
            )
        except FileNotFoundError as e:
            raise PiNotInstalledError(
                f"Failed to execute Pi binary: {e}. Check that Node.js and Pi are installed."
            ) from e
        except Exception as e:
            raise PiAgentException(f"Failed to spawn Pi subprocess: {e}") from e

        captured_events: List[Dict[str, Any]] = []
        stderr_output: List[str] = []

        async def read_stderr() -> None:
            """Continuously consume stderr to prevent buffer deadlocks."""
            try:
                assert proc.stderr is not None
                while not proc.stderr.at_eof():
                    line = await proc.stderr.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if decoded:
                        stderr_output.append(decoded)
            except (asyncio.CancelledError, Exception):
                pass

        async def run_rpc_session() -> PiGenerationResult:
            """Handle stdin write and stdout event consumption."""
            assert proc.stdin is not None
            assert proc.stdout is not None

            # 1. Send the prompt command
            cmd_payload = json.dumps(prompt_command) + "\n"
            proc.stdin.write(cmd_payload.encode("utf-8"))
            await proc.stdin.drain()

            prompt_accepted = False
            settled = False

            while not proc.stdout.at_eof():
                raw_line = await proc.stdout.readline()
                if not raw_line:
                    break

                line_str = raw_line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue

                try:
                    record = json.loads(line_str)
                except json.JSONDecodeError as err:
                    logger.warning("Unparseable JSONL record from Pi stdout: %s", line_str)
                    raise PiOutputParseError(
                        f"Failed to parse JSONL line from Pi: {line_str[:120]}"
                    ) from err

                captured_events.append(record)
                rec_type = record.get("type")

                # Handle immediate command response
                if rec_type == "response" and record.get("command") == "prompt":
                    if record.get("id") == req_id:
                        if not record.get("success", False):
                            err_msg = record.get("error") or record.get("data", {}).get("message")
                            detected_err = self._detect_provider_error(
                                events=[record],
                                stderr_output=stderr_output,
                                provider=validated_provider,
                                model=validated_model,
                            )
                            if detected_err is not None:
                                raise detected_err
                            raise PiPromptRejectedError(
                                f"Pi rejected prompt: {err_msg or 'Unknown error'}"
                            )
                        prompt_accepted = True

                # Handle settlement / completion events
                if rec_type == "agent_settled":
                    settled = True
                    break

                if rec_type == "agent_end" and not record.get("willRetry", False):
                    # In some Pi versions, agent_settled immediately follows agent_end.
                    # We record settled if agent_settled is not strictly required.
                    settled = True
                    break

            # If prompt was not accepted or generation did not settle, ensure available stderr is collected
            if not prompt_accepted or not settled:
                # Yield execution momentarily to allow background stderr reader task to drain
                await asyncio.sleep(0)
                # If stderr pipe has remaining lines, drain them safely without blocking
                if getattr(proc, "stderr", None) and hasattr(proc.stderr, "at_eof"):
                    while not proc.stderr.at_eof():
                        try:
                            line_bytes = await asyncio.wait_for(proc.stderr.readline(), timeout=0.1)
                            if not line_bytes:
                                break
                            dec = line_bytes.decode("utf-8", errors="replace").strip()
                            if dec and dec not in stderr_output:
                                stderr_output.append(dec)
                        except (asyncio.TimeoutError, Exception):
                            break

            # Prioritize genuine provider error detection over reporting termination errors
            detected_error = self._detect_provider_error(
                events=captured_events,
                stderr_output=stderr_output,
                provider=validated_provider,
                model=validated_model,
            )
            if detected_error is not None:
                category = (
                    detected_error.category
                    if isinstance(detected_error, PiProviderError)
                    else type(detected_error).__name__
                )
                logger.warning(
                    "Pi generation provider failure: category=%s, provider=%s, model=%s, req_id=%s",
                    category,
                    validated_provider,
                    validated_model,
                    req_id,
                )
                raise detected_error

            if not prompt_accepted:
                raise PiProcessTerminatedError(
                    "Pi subprocess terminated without accepting the prompt command.",
                    details=" | ".join(stderr_output[-5:]),
                )

            if not settled:
                raise PiProcessTerminatedError(
                    "Pi subprocess closed stdout stream before settling the assistant run.",
                    details=" | ".join(stderr_output[-5:]),
                )

            assistant_text = self._extract_assistant_text(captured_events)
            if not assistant_text:
                # Find terminal assistant message stopReason
                terminal_stop_reason = None
                for ev in reversed(captured_events):
                    if ev.get("type") in ("message_end", "turn_end"):
                        m = ev.get("message", {})
                        if m.get("role") == "assistant":
                            terminal_stop_reason = m.get("stopReason")
                            break
                    elif ev.get("type") == "agent_end":
                        for m in reversed(ev.get("messages", [])):
                            if m.get("role") == "assistant":
                                terminal_stop_reason = m.get("stopReason")
                                break
                        if terminal_stop_reason:
                            break

                if terminal_stop_reason in ("stop", "length", "toolUse"):
                    raise PiEmptyResponseError(
                        f"Pi Coding Agent completed execution ({validated_provider}/{validated_model}) but produced an empty assistant response.",
                        provider=validated_provider,
                        model=validated_model,
                        details=" | ".join(stderr_output[-5:]) if stderr_output else None,
                        retryable=False,
                    )

                raise PiProcessTerminatedError(
                    f"Pi subprocess completed without producing an assistant message ({validated_provider}/{validated_model}).",
                    details=" | ".join(stderr_output[-5:]) if stderr_output else None,
                )

            return PiGenerationResult(
                text=assistant_text,
                provider=validated_provider,
                model=validated_model,
                raw_events=captured_events,
            )

        stderr_task = asyncio.create_task(read_stderr())
        is_timeout = False
        is_cancelled = False

        try:
            result = await asyncio.wait_for(run_rpc_session(), timeout=float(timeout))
            duration = asyncio.get_event_loop().time() - start_time
            if getattr(self.settings, "pi_capture_events", False):
                try:
                    from backend.app.agent.evidence_collector import record_pi_evidence

                    record_pi_evidence(
                        project_root=self.project_root,
                        settings=self.settings,
                        request_id=req_id,
                        provider=validated_provider,
                        model=validated_model,
                        raw_events=captured_events,
                        duration_seconds=duration,
                        outcome="success",
                        assistant_text=result.text,
                    )
                except Exception as cap_err:
                    logger.debug("Evidence capture non-blocking error: %s", cap_err)
            return result
        except asyncio.TimeoutError as te:
            is_timeout = True
            duration = asyncio.get_event_loop().time() - start_time
            if getattr(self.settings, "pi_capture_events", False):
                try:
                    from backend.app.agent.evidence_collector import record_pi_evidence

                    record_pi_evidence(
                        project_root=self.project_root,
                        settings=self.settings,
                        request_id=req_id,
                        provider=validated_provider,
                        model=validated_model,
                        raw_events=captured_events,
                        duration_seconds=duration,
                        outcome="timeout",
                        error_message=f"Timeout after {timeout}s",
                    )
                except Exception as cap_err:
                    logger.debug("Evidence capture non-blocking error: %s", cap_err)
            logger.error("Pi Coding Agent generation timed out after %s seconds", timeout)
            raise PiTimeoutError(
                f"Pi Coding Agent generation timed out after {timeout} seconds.",
                details=" | ".join(stderr_output[-5:]),
            ) from te
        except asyncio.CancelledError:
            is_cancelled = True
            raise
        except Exception as exc:
            duration = asyncio.get_event_loop().time() - start_time
            if getattr(self.settings, "pi_capture_events", False):
                try:
                    from backend.app.agent.evidence_collector import record_pi_evidence

                    record_pi_evidence(
                        project_root=self.project_root,
                        settings=self.settings,
                        request_id=req_id,
                        provider=validated_provider,
                        model=validated_model,
                        raw_events=captured_events,
                        duration_seconds=duration,
                        outcome="error",
                        error_message=str(exc),
                    )
                except Exception as cap_err:
                    logger.debug("Evidence capture non-blocking error: %s", cap_err)
            raise
        finally:
            await self._cleanup_subprocess(
                proc=proc,
                stderr_task=stderr_task,
                is_timeout=is_timeout,
                is_cancelled=is_cancelled,
            )

    async def _cleanup_subprocess(
        self,
        proc: Any,
        stderr_task: Optional[asyncio.Task] = None,
        is_timeout: bool = False,
        is_cancelled: bool = False,
    ) -> None:
        """Safely terminate the Pi subprocess and release all pipe transports.

        Ensures full Windows ProactorEventLoop and POSIX compatibility without pipe deadlock.
        """
        # 1. Safely close stdin pipe first so child process detects EOF
        if getattr(proc, "stdin", None):
            try:
                is_closing = False
                if hasattr(proc.stdin, "is_closing"):
                    val = proc.stdin.is_closing()
                    if isinstance(val, bool):
                        is_closing = val
                if not is_closing and hasattr(proc.stdin, "close"):
                    proc.stdin.close()
                if hasattr(proc.stdin, "wait_closed"):
                    wait_coro = proc.stdin.wait_closed()
                    if asyncio.iscoroutine(wait_coro):
                        await wait_coro
            except Exception as e:
                logger.debug("Error closing proc.stdin: %s", e)

        # 2. Terminate immediately if timeout or cancelled
        if getattr(proc, "returncode", None) is None and (is_timeout or is_cancelled):
            try:
                if hasattr(proc, "terminate"):
                    proc.terminate()
            except Exception as e:
                logger.debug("Error terminating subprocess on timeout/cancel: %s", e)

        # 3. Concurrently drain pipes and wait for subprocess exit to avoid pipe buffer deadlocks
        async def _drain_stdout() -> None:
            if getattr(proc, "stdout", None) and hasattr(proc.stdout, "at_eof"):
                try:
                    if not proc.stdout.at_eof() and hasattr(proc.stdout, "read"):
                        read_coro = proc.stdout.read()
                        if asyncio.iscoroutine(read_coro):
                            await read_coro
                except Exception as e:
                    logger.debug("Error draining proc.stdout: %s", e)

        async def _drain_stderr() -> None:
            if stderr_task and not stderr_task.done():
                try:
                    await stderr_task
                except (asyncio.CancelledError, Exception):
                    pass

        async def _wait_process() -> None:
            if getattr(proc, "returncode", None) is None and hasattr(proc, "wait"):
                try:
                    wait_coro = proc.wait()
                    if asyncio.iscoroutine(wait_coro):
                        await wait_coro
                except Exception as e:
                    logger.debug("Error waiting for subprocess: %s", e)

        drain_coros = [_drain_stdout(), _drain_stderr()]
        if getattr(proc, "returncode", None) is None:
            drain_coros.append(_wait_process())

        try:
            timeout_limit = 2.0 if (is_timeout or is_cancelled) else 1.0
            await asyncio.wait_for(
                asyncio.gather(*drain_coros, return_exceptions=True),
                timeout=timeout_limit,
            )
        except asyncio.TimeoutError:
            # Subprocess did not exit within graceful window; force terminate then kill
            if getattr(proc, "returncode", None) is None:
                try:
                    if hasattr(proc, "terminate"):
                        proc.terminate()
                    if hasattr(proc, "wait"):
                        wait_coro = proc.wait()
                        if asyncio.iscoroutine(wait_coro):
                            await asyncio.wait_for(wait_coro, timeout=1.5)
                except (asyncio.TimeoutError, Exception):
                    try:
                        if hasattr(proc, "kill"):
                            proc.kill()
                        if hasattr(proc, "wait"):
                            wait_coro = proc.wait()
                            if asyncio.iscoroutine(wait_coro):
                                await wait_coro
                    except Exception as e:
                        logger.debug("Error force-killing subprocess: %s", e)

        # 4. Ensure stderr_task is cancelled and awaited if still pending
        if stderr_task and not stderr_task.done():
            stderr_task.cancel()
            try:
                await stderr_task
            except (asyncio.CancelledError, Exception):
                pass

        # 5. Explicitly close underlying transport if still open
        # Process does not have a public close() method; _transport represents BaseSubprocessTransport
        transport = getattr(proc, "_transport", None)
        if transport is not None:
            try:
                is_closing = False
                if hasattr(transport, "is_closing"):
                    val = transport.is_closing()
                    if isinstance(val, bool):
                        is_closing = val
                if not is_closing and hasattr(transport, "close"):
                    transport.close()
            except Exception as e:
                logger.debug("Error closing subprocess transport: %s", e)

        # 6. Yield briefly to event loop so Proactor/IOCP callbacks can process closures
        try:
            await asyncio.sleep(0)
        except Exception:
            pass
