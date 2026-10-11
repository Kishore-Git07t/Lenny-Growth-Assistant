"""Agent orchestration service connecting FastAPI sessions, PostgreSQL persistence, and Pi RPC."""

import logging
from typing import List, Optional
import uuid

from fastapi import Depends, HTTPException, status
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
from backend.app.agent.pi_client import PiClient
from backend.app.agent.rag import (
    DEFAULT_RAG_MAX_CHARS_PER_PASSAGE,
    DEFAULT_RAG_MAX_PASSAGES,
    DEFAULT_RAG_MAX_TOTAL_CHARS,
    EvidenceEntry,
    extract_cited_indices,
    format_citation_retry_prompt,
    format_rag_prompt,
    prepare_bounded_evidence,
    validate_and_sanitize_citations,
)
from backend.app.config import Settings, get_settings
from backend.app.embeddings.client import EmbeddingError
from backend.app.models.message import ChatMessage
from backend.app.repositories import (
    create_message,
    get_session_by_id,
    list_messages_by_session,
)
from backend.app.retrieval.schemas import CitationSource, IndexCoverage
from backend.app.retrieval.service import SemanticRetrievalService
from backend.app.schemas.agent import AgentRespondResponse
from backend.app.schemas.message import MessageResponse

logger = logging.getLogger(__name__)


PROTOTYPE_SYSTEM_PROMPT = (
    "You are the Lenny Growth Assistant, a specialist AI copilot for product management, "
    "growth strategy, retention, and startup execution.\n\n"
    "[System Operational Notice - Prototype Stage]:\n"
    "Podcast transcript chunk ingestion and grounded vector retrieval are currently scheduled for "
    "Phase 3 Step 3.2 and are not yet active in this build.\n"
    "- Do NOT fabricate transcript quotations or invent podcast episode citations.\n"
    "- Do NOT claim you have searched Lenny's podcast transcript database.\n"
    "- Provide clear, actionable, structured conceptual guidance based on established product management "
    "frameworks (e.g. retention curves, growth loops, PLG vs SLG, customer discovery).\n"
    "- Note transparently that verifiable episode quotations will be available in the upcoming RAG release."
)


class AgentService:
    """Coordinates conversational sessions, semantic retrieval, bounded RAG prompts, and Pi RPC."""

    def __init__(
        self,
        pi_client: Optional[PiClient] = None,
        retrieval_service: Optional[SemanticRetrievalService] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.pi_client = pi_client or PiClient(settings=self.settings)
        if self.settings and self.pi_client:
            self.pi_client.settings = self.settings
        self.retrieval_service = retrieval_service

    @staticmethod
    def format_prompt(
        history: List[ChatMessage],
        current_content: str,
        evidence_entries: Optional[List[EvidenceEntry]] = None,
        coverage: Optional[IndexCoverage] = None,
        disclaimer: Optional[str] = None,
        retrieval_status: Optional[str] = None,
    ) -> str:
        """Assemble prompt with backward compatibility for legacy tests and bounded RAG."""
        if evidence_entries is None and coverage is None and retrieval_status is None:
            # Preserved for backward-compatibility with prototype tests
            prompt_parts = [PROTOTYPE_SYSTEM_PROMPT, "\n\n--- Conversation History ---"]
            bounded_history = history[-10:] if len(history) > 10 else history
            for msg in bounded_history:
                role_label = "User" if msg.role == "user" else "Assistant"
                prompt_parts.append(f"\n{role_label}: {msg.content}")
            prompt_parts.append(f"\nUser: {current_content}")
            prompt_parts.append("\nAssistant:")
            return "".join(prompt_parts)

        return format_rag_prompt(
            history=history,
            current_content=current_content,
            evidence_entries=evidence_entries or [],
            coverage=coverage,
            disclaimer=disclaimer,
            retrieval_status=retrieval_status,
        )

    async def generate_session_response(
        self,
        db: Session,
        session_id: uuid.UUID,
        content: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> AgentRespondResponse:
        """Validate session, retrieve evidence, invoke genuine Pi agent, validate citations, and persist turn.

        Guarantees:
            1. Validates that the session exists in PostgreSQL; raises HTTP 404 otherwise.
            2. Idempotent Retry Handling: If the last message in the session is an unanswered user
               message identical to this request, reuses it rather than duplicating database records.
            3. Persists the user message in PostgreSQL prior to invoking retrieval or Pi.
            4. Executes semantic retrieval over podcast transcripts using pgvector.
            5. Bounds RAG context to preserve the local 1.5B model's context window.
            6. Invokes genuine Pi Coding Agent RPC subprocess with disabled dangerous tools.
            7. Validates and sanitizes citation references, stripping unsupported markers.
            8. Employs a conservative grounded fallback if the local model produces uncited claims.
            9. Stores structured citation metadata and provenance in PostgreSQL.
        """
        # 1. Validate session existence
        session = get_session_by_id(db=db, session_id=session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session with ID '{session_id}' not found.",
            )

        # 2. Retrieve existing message history for the session
        existing_messages, _ = list_messages_by_session(
            db=db, session_id=session_id, limit=50, offset=0
        )

        # 3. Check for idempotent retry
        is_retry = False
        user_message: ChatMessage

        if (
            existing_messages
            and existing_messages[-1].role == "user"
            and existing_messages[-1].content == content
        ):
            # Previous attempt failed after saving user message; reuse on retry
            user_message = existing_messages[-1]
            is_retry = True
            logger.info("Reusing existing uncompleted user message on retry: %s", user_message.id)
            history_for_prompt = existing_messages[:-1]
        else:
            # Persist new user message
            user_message = create_message(
                db=db,
                session_id=session_id,
                role="user",
                content=content,
                source_metadata=None,
            )
            history_for_prompt = existing_messages

        # 3.5 Early provider credential validation before retrieval or subprocess launch
        try:
            self.pi_client.validate_provider_model(provider, model)
        except PiConfigurationError as e:
            logger.warning("Provider configuration validation failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "pi_configuration_error",
                    "message": str(e),
                    "retryable": False,
                },
            )

        # 4. Perform semantic vector retrieval over transcript passages
        retrieval_svc = self.retrieval_service or SemanticRetrievalService(db=db)
        try:
            retrieval_res = retrieval_svc.retrieve(
                query=content,
                top_k=getattr(self.settings, "rag_top_k", 5),
            )
        except EmbeddingError as e:
            logger.error("Ollama query embedding failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "embedding_unavailable",
                    "message": f"Query embedding service unavailable: {e}",
                    "retryable": True,
                },
            )
        except Exception as e:
            logger.error("Semantic retrieval failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "retrieval_error",
                    "message": f"Semantic retrieval failed: {e}",
                    "retryable": True,
                },
            )

        # 5. Build bounded RAG context from retrieved passages
        evidence_entries = prepare_bounded_evidence(
            sources=retrieval_res.items,
            query=content,
            max_passages=getattr(self.settings, "rag_max_passages_in_prompt", DEFAULT_RAG_MAX_PASSAGES),
            max_chars_per_passage=getattr(self.settings, "rag_max_chars_per_passage", DEFAULT_RAG_MAX_CHARS_PER_PASSAGE),
            max_total_chars=getattr(self.settings, "rag_max_total_evidence_chars", DEFAULT_RAG_MAX_TOTAL_CHARS),
        )

        prompt = self.format_prompt(
            history=history_for_prompt,
            current_content=content,
            evidence_entries=evidence_entries,
            coverage=retrieval_res.coverage,
            disclaimer=retrieval_res.disclaimer,
            retrieval_status=retrieval_res.status,
        )

        # 6. Invoke genuine Pi Coding Agent RPC subprocess
        try:
            result = await self.pi_client.generate_response(
                prompt=prompt,
                provider=provider,
                model=model,
            )
        except PiNotInstalledError as e:
            logger.error("Pi Coding Agent not installed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "pi_not_installed",
                    "message": str(e),
                    "retryable": True,
                },
            )
        except PiTimeoutError as e:
            logger.error("Pi Coding Agent generation timed out: %s", e)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail={
                    "error": "pi_timeout",
                    "message": str(e),
                    "retryable": True,
                },
            )
        except (PiAuthenticationError, PiConfigurationError) as e:
            logger.error("Pi authentication/configuration error: %s", e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "pi_configuration_error",
                    "message": str(e),
                    "retryable": False,
                },
            )
        except PiRateLimitError as e:
            logger.warning("Pi provider rate limit exceeded: %s", e)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "pi_rate_limit",
                    "message": str(e),
                    "retryable": True,
                },
            )
        except (PiModelNotFoundError, PiNetworkError, PiProviderError) as e:
            logger.error("Pi provider error: %s", e)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "pi_provider_error",
                    "message": str(e),
                    "retryable": True,
                },
            )
        except PiOutputParseError as e:
            logger.info("Pi generation diagnostic: outcome=pi_rpc_parsing_error, error_type=PiOutputParseError")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "pi_runtime_error",
                    "message": str(e),
                    "retryable": True,
                },
            )
        except PiEmptyResponseError as e:
            logger.warning("Pi model completed with empty text: %s", e)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "pi_empty_response",
                    "message": str(e),
                    "retryable": True,
                },
            )
        except (PiPromptRejectedError, PiProcessTerminatedError, PiAgentException) as e:
            logger.error("Pi Coding Agent runtime execution failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "pi_runtime_error",
                    "message": str(e),
                    "retryable": True,
                },
            )

        # Diagnostic evaluation of primary Pi response
        resp_len = len(result.text.strip()) if result.text else 0
        detected_markers = extract_cited_indices(result.text) if result.text else []
        valid_indices = {entry.index for entry in evidence_entries}
        valid_markers = [idx for idx in detected_markers if idx in valid_indices]

        if resp_len == 0:
            outcome = "pi_empty_response"
        elif not detected_markers:
            outcome = "pi_uncited_response"
        elif not valid_markers:
            outcome = "pi_invalid_citations"
        else:
            outcome = "pi_valid_cited_response"

        if outcome == "pi_valid_cited_response":
            logger.info(
                "Pi generation diagnostic: outcome=%s, response_length=%d, valid_citations=%s",
                outcome,
                resp_len,
                valid_markers,
            )
        else:
            logger.warning(
                "Pi generation diagnostic: outcome=%s, response_length=%d, detected_citations=%s",
                outcome,
                resp_len,
                detected_markers,
            )

        # Bounded citation-correction retry: if output was uncited or citations were invalid, attempt AT MOST ONE retry
        if outcome in ("pi_uncited_response", "pi_invalid_citations") and resp_len > 0 and evidence_entries:
            logger.warning(
                "Pi diagnostic: initiating citation-correction retry: prior_outcome=%s, response_length=%d",
                outcome,
                resp_len,
            )
            retry_prompt = format_citation_retry_prompt(
                prompt=prompt,
                draft_response=result.text,
                evidence_entries=evidence_entries,
            )
            try:
                retry_timeout = min(15, getattr(self.settings, "pi_agent_timeout_seconds", 30))
                retry_result = await self.pi_client.generate_response(
                    prompt=retry_prompt,
                    provider=provider,
                    model=model,
                    timeout_seconds=retry_timeout,
                )
                retry_len = len(retry_result.text.strip()) if retry_result.text else 0
                retry_markers = extract_cited_indices(retry_result.text) if retry_result.text else []
                retry_valid = [idx for idx in retry_markers if idx in valid_indices]

                if retry_valid:
                    logger.info(
                        "Pi diagnostic: citation_retry=successful, outcome=pi_valid_cited_response, response_length=%d, valid_citations=%s",
                        retry_len,
                        retry_valid,
                    )
                    result = retry_result
                else:
                    retry_outcome = "pi_empty_response" if retry_len == 0 else ("pi_uncited_response" if not retry_markers else "pi_invalid_citations")
                    logger.warning(
                        "Pi diagnostic: citation_retry=failed, outcome=%s, response_length=%d, detected_citations=%s",
                        retry_outcome,
                        retry_len,
                        retry_markers,
                    )
            except Exception as retry_err:
                logger.warning(
                    "Pi diagnostic: citation_retry=failed, error_type=%s",
                    type(retry_err).__name__,
                )

        # 7. Validate and sanitize citation references in assistant output
        sanitized_text, validated_citations = validate_and_sanitize_citations(
            response_text=result.text,
            evidence_entries=evidence_entries,
            query=content,
            fallback_on_uncited=True,
        )


        # 8. Persist verified assistant response and citation metadata in PostgreSQL
        assistant_metadata = {
            "provider": result.provider,
            "model": result.model,
            "agent_framework": "pi_coding_agent",
            "retrieval_status": retrieval_res.status,
            "coverage": retrieval_res.coverage.model_dump(),
            "disclaimer": retrieval_res.disclaimer,
            "citations": [c.model_dump(mode="json") for c in validated_citations],
        }
        assistant_message = create_message(
            db=db,
            session_id=session_id,
            role="assistant",
            content=sanitized_text,
            source_metadata=assistant_metadata,
        )

        return AgentRespondResponse(
            session_id=session_id,
            user_message=MessageResponse.model_validate(user_message),
            assistant_message=MessageResponse.model_validate(assistant_message),
            provider=result.provider,
            model=result.model,
            retried=is_retry,
            citations=validated_citations,
            retrieval_status=retrieval_res.status,
            coverage=retrieval_res.coverage,
            disclaimer=retrieval_res.disclaimer,
        )


def get_agent_service(settings: Settings = Depends(get_settings)) -> AgentService:
    """Dependency provider returning an AgentService instance configured with current settings."""
    return AgentService(settings=settings)

