import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SECRET_PATTERNS = [
    (re.compile(r"AIza[0-9A-Za-z_-]{15,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"sk-[A-Za-z0-9_-]{10,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"bearer\s+[A-Za-z0-9._~+/-]+", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
]


def sanitize_secret_text(text: Optional[str], settings: Optional[Any] = None) -> str:
    """Redact sensitive API keys, tokens, and authorization headers from diagnostic text."""
    if not text:
        return ""
    result = str(text)

    # 1. Explicitly redact known configured secrets if settings are available
    try:
        from backend.app.config import get_settings
        cfg = settings or get_settings()
        for secret in (
            getattr(cfg, "gemini_api_key", None),
            getattr(cfg, "openai_api_key", None),
            getattr(cfg, "anthropic_api_key", None),
        ):
            if secret and len(str(secret).strip()) >= 6:
                result = result.replace(str(secret).strip(), "[REDACTED_API_KEY]")
    except Exception:
        pass

    # 2. Redact pattern-matched credentials
    for pat, replacement in _SECRET_PATTERNS:
        result = pat.sub(replacement, result)

    return result


class PiAgentException(Exception):
    """Base exception for all Pi Coding Agent runtime errors."""

    def __init__(self, message: str, details: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


class PiNotInstalledError(PiAgentException):
    """Raised when the Pi Coding Agent executable or package cannot be located."""
    pass


class PiConfigurationError(PiAgentException):
    """Raised when Pi or model provider configuration is invalid or missing credentials."""
    pass


class PiPromptRejectedError(PiAgentException):
    """Raised when the Pi runtime explicitly rejects a prompt command."""
    pass


class PiTimeoutError(PiAgentException):
    """Raised when a Pi RPC command or generation run exceeds the configured timeout."""
    pass


class PiProcessTerminatedError(PiAgentException):
    """Raised when the Pi subprocess terminates unexpectedly or exits with a non-zero code."""
    pass


class PiOutputParseError(PiAgentException):
    """Raised when the Pi runtime emits malformed, unparseable, or invalid JSONL."""
    pass


class PiProviderError(PiAgentException):
    """Raised when an upstream LLM provider returns an API error during Pi generation."""

    def __init__(
        self,
        message: str,
        category: str = "provider_error",
        provider: Optional[str] = None,
        model: Optional[str] = None,
        details: Optional[str] = None,
        retryable: bool = False,
    ) -> None:
        clean_msg = sanitize_secret_text(message) if message else message
        clean_details = sanitize_secret_text(details) if details else details
        super().__init__(clean_msg, details=clean_details)
        self.category = category
        self.provider = provider
        self.model = model
        self.retryable = retryable


class PiAuthenticationError(PiProviderError):
    """Raised when provider authentication fails (e.g. invalid or revoked API key)."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        details: Optional[str] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message=message,
            category="authentication_error",
            provider=provider,
            model=model,
            details=details,
            retryable=retryable,
        )


class PiRateLimitError(PiProviderError):
    """Raised when provider rate limit or quota is exceeded."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        details: Optional[str] = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(
            message=message,
            category="rate_limit_error",
            provider=provider,
            model=model,
            details=details,
            retryable=retryable,
        )


class PiModelNotFoundError(PiProviderError):
    """Raised when requested model is invalid or not found on provider."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        details: Optional[str] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message=message,
            category="model_not_found",
            provider=provider,
            model=model,
            details=details,
            retryable=retryable,
        )


class PiNetworkError(PiProviderError):
    """Raised when network connection to provider fails."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        details: Optional[str] = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(
            message=message,
            category="network_error",
            provider=provider,
            model=model,
            details=details,
            retryable=retryable,
        )


class PiEmptyResponseError(PiAgentException):
    """Raised when the model run succeeds normally (stopReason='stop') but generated empty text."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        details: Optional[str] = None,
        retryable: bool = False,
    ) -> None:
        clean_msg = sanitize_secret_text(message) if message else message
        clean_details = sanitize_secret_text(details) if details else details
        super().__init__(clean_msg, details=clean_details)
        self.provider = provider
        self.model = model
        self.retryable = retryable

