"""Pi Coding Agent integration package."""

from backend.app.agent.exceptions import (
    PiAgentException,
    PiConfigurationError,
    PiNotInstalledError,
    PiOutputParseError,
    PiProcessTerminatedError,
    PiPromptRejectedError,
    PiTimeoutError,
)
from backend.app.agent.pi_client import PiClient, PiGenerationResult
from backend.app.agent.rag import (
    EvidenceEntry,
    build_grounded_system_prompt,
    format_rag_prompt,
    prepare_bounded_evidence,
    validate_and_sanitize_citations,
)
from backend.app.agent.service import AgentService, get_agent_service
from backend.app.agent.skills.ship30_essay import Ship30EssayOrchestrator
from backend.app.agent.skills.html_artifact import HtmlArtifactOrchestrator

__all__ = [
    "PiAgentException",
    "PiConfigurationError",
    "PiNotInstalledError",
    "PiOutputParseError",
    "PiProcessTerminatedError",
    "PiPromptRejectedError",
    "PiTimeoutError",
    "PiClient",
    "PiGenerationResult",
    "EvidenceEntry",
    "prepare_bounded_evidence",
    "build_grounded_system_prompt",
    "format_rag_prompt",
    "validate_and_sanitize_citations",
    "AgentService",
    "get_agent_service",
    "Ship30EssayOrchestrator",
    "HtmlArtifactOrchestrator",
]

