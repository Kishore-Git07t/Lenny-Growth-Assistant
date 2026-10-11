"""Orchestrator for AI-driven HTML/CSS artifact generation, sanitization, and persistence."""

from datetime import datetime, timezone
import logging
from typing import List, Optional
import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.app.agent.exceptions import (
    PiAgentException,
    PiAuthenticationError,
    PiConfigurationError,
    PiEmptyResponseError,
    PiProviderError,
    PiRateLimitError,
    PiTimeoutError,
)
from backend.app.agent.pi_client import PiClient
from backend.app.agent.rag import prepare_bounded_evidence
from backend.app.agent.skills.html_artifact.prompts import (
    build_artifact_prompt,
    generate_fallback_artifact,
    parse_model_artifact_output,
)
from backend.app.agent.skills.html_artifact.sanitizer import (
    build_sandboxed_preview,
    sanitize_css,
    sanitize_html,
)
from backend.app.config import Settings, get_settings
from backend.app.repositories import create_message, get_session_by_id
from backend.app.retrieval.schemas import CitationSource, IndexCoverage, RetrievalResponse
from backend.app.retrieval.service import SemanticRetrievalService
from backend.app.schemas.artifact import ArtifactResponse

logger = logging.getLogger(__name__)

# Keywords indicating that Lenny's podcast transcript context is relevant
PODCAST_INTENT_KEYWORDS = {
    "lenny",
    "podcast",
    "episode",
    "guest",
    "jason lemkin",
    "retention",
    "growth",
    "pricing",
    "onboarding",
    "saas",
    "plg",
    "sales",
    "metric",
    "strategy",
    "playbook",
    "activation",
}


class HtmlArtifactOrchestrator:
    """Coordinates generation, sanitization, validation, and persistence of HTML/CSS artifacts."""

    def __init__(
        self,
        pi_client: Optional[PiClient] = None,
        retrieval_service: Optional[SemanticRetrievalService] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.pi_client = pi_client or PiClient(settings=self.settings)
        self.retrieval_service = retrieval_service

    async def generate_artifact(
        self,
        session_id: uuid.UUID,
        prompt: str,
        title: Optional[str] = None,
        artifact_type: Optional[str] = "landing_page",
        style_preferences: Optional[str] = None,
        include_podcast_context: bool = True,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> ArtifactResponse:
        """Generate, sanitize, and persist a professional HTML/CSS artifact.

        Workflow:
            1. Validate parent session existence in database.
            2. Optionally retrieve relevant podcast evidence if requested.
            3. Build structured generation prompt for Pi Coding Agent.
            4. Invoke Pi Coding Agent subprocess to generate HTML and CSS.
            5. Parse model output into discrete title, HTML, and CSS blocks.
            6. Perform server-side security sanitization (stripping scripts, event handlers, etc.).
            7. Assemble a self-contained, CSP-enforced sandboxed preview document.
            8. Persist the artifact in PostgreSQL as an assistant message with metadata.
            9. Return structured ArtifactResponse contract.
        """
        # 1. Validate session existence
        if db is not None:
            db_session = get_session_by_id(db=db, session_id=session_id)
            if not db_session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Session with ID '{session_id}' not found.",
                )

        clean_prompt = prompt.strip()
        clean_type = (artifact_type or "landing_page").strip()
        clean_title = title.strip() if title else None

        active_provider = (provider or self.settings.llm_provider or "ollama").strip().lower()
        if active_provider in ("google", "gemini"):
            active_provider = "google"
            active_model = model or getattr(self.settings, "gemini_model", "gemini-2.5-flash")
        elif active_provider == "ollama":
            active_model = model or self.settings.ollama_model or "qwen2.5:1.5b"
        elif active_provider == "openai":
            active_model = model or getattr(self.settings, "openai_model", "gpt-4o-mini")
        else:
            active_model = model or getattr(self.settings, "anthropic_model", "claude-3-5-sonnet-20241022")

        # 2. Check for podcast context relevance
        citations: List[CitationSource] = []
        coverage: Optional[IndexCoverage] = None
        evidence_entries = []
        disclaimer: Optional[str] = None

        should_retrieve = include_podcast_context and any(
            kw in clean_prompt.lower() for kw in PODCAST_INTENT_KEYWORDS
        )

        if should_retrieve:
            retrieval_svc = self.retrieval_service or (
                SemanticRetrievalService(db=db) if db is not None else None
            )
            if retrieval_svc is not None:
                try:
                    retrieval_res: RetrievalResponse = retrieval_svc.retrieve(
                        query=clean_prompt,
                        top_k=3,
                    )
                    if retrieval_res.status == "success" and retrieval_res.items:
                        citations = retrieval_res.items
                        coverage = retrieval_res.coverage
                        disclaimer = retrieval_res.disclaimer
                        evidence_entries = prepare_bounded_evidence(
                            sources=citations,
                            query=clean_prompt,
                            max_total_chars=4000,
                            max_chars_per_passage=1500,
                        )
                except Exception as e:
                    logger.warning("Optional transcript retrieval failed for artifact: %s", e)
            else:
                logger.info(
                    "Optional podcast retrieval skipped: database session and retrieval service not provided."
                )

        # 3. Build generation prompt
        agent_prompt = build_artifact_prompt(
            user_prompt=clean_prompt,
            title=clean_title,
            artifact_type=clean_type,
            style_preferences=style_preferences,
            evidence_entries=evidence_entries if evidence_entries else None,
        )

        # 4. Invoke genuine Pi Coding Agent
        logger.info(
            "Invoking Pi Coding Agent for HTML/CSS artifact generation (session_id=%s, type=%s, provider=%s, model=%s)",
            session_id,
            clean_type,
            active_provider,
            active_model,
        )

        status_label = "completed"
        diagnostics: List[str] = []
        raw_text = ""

        timeout_budget = min(self.settings.pi_agent_timeout_seconds, 180)
        try:
            gen_res = await self.pi_client.generate_response(
                prompt=agent_prompt,
                provider=active_provider,
                model=active_model,
                timeout_seconds=timeout_budget,
            )
            raw_text = gen_res.text or ""
        except (PiAuthenticationError, PiConfigurationError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "pi_configuration_error", "message": str(e), "retryable": False},
            )
        except PiRateLimitError as e:
            logger.warning("Pi artifact generation rate limit reached: %s", e)
            status_label = "partial"
            diagnostics.append(f"Provider rate limit reached: {str(e)}; applied fallback layout")
        except PiTimeoutError as e:
            logger.warning("Pi artifact generation timed out after %s seconds: %s", timeout_budget, e)
            status_label = "partial"
            diagnostics.append("Generation timed out; applied high-quality fallback layout")
        except (PiProviderError, PiEmptyResponseError, PiAgentException) as e:
            logger.error("Pi artifact generation failed: %s", e)
            status_label = "partial"
            diagnostics.append(f"Model generation error: {str(e)}; applied fallback layout")
        except Exception as e:
            logger.error("Unexpected error during artifact generation: %s", e)
            status_label = "partial"
            diagnostics.append(f"Unexpected generation error: {str(e)}; applied fallback layout")


        # 5. Parse output or apply fallback
        extracted_title, description, raw_html, raw_css = parse_model_artifact_output(
            raw_text=raw_text,
            default_title=clean_title,
        )

        # If both HTML and CSS are missing, apply robust responsive fallback
        if not raw_html or not raw_css:
            status_label = "partial"
            fb_title, fb_html, fb_css = generate_fallback_artifact(
                prompt=clean_prompt,
                title=clean_title or extracted_title,
                artifact_type=clean_type,
            )
            final_title = fb_title
            raw_html = raw_html or fb_html
            raw_css = raw_css or fb_css
            diagnostics.append("Model output missing complete code blocks; applied structured layout components")
        else:
            final_title = extracted_title

        # 6. Sanitize HTML and CSS
        sanitized_html, html_diags = sanitize_html(raw_html)
        sanitized_css, css_diags = sanitize_css(raw_css)
        diagnostics.extend(html_diags)
        diagnostics.extend(css_diags)

        # If severe sanitization stripped critical content, record advisory
        if html_diags or css_diags:
            diagnostics.append("Security sanitization removed disallowed active elements or unsafe styles")

        # 7. Assemble sandboxed preview document
        combined_preview = build_sandboxed_preview(
            html=sanitized_html,
            css=sanitized_css,
            title=final_title,
        )

        # 8. Persist into PostgreSQL
        now = datetime.now(timezone.utc)
        message_id = uuid.uuid4()
        is_persisted = False

        if db is not None:
            try:
                # User prompt message
                create_message(
                    db=db,
                    session_id=session_id,
                    role="user",
                    content=clean_prompt,
                    source_metadata={"request_type": "artifact_generate", "artifact_type": clean_type},
                )

                # Assistant artifact message: ensure all nested Pydantic models (with UUIDs)
                # are serialized in JSON-mode so PostgreSQL JSON/JSONB encoders receive string UUIDs.
                assistant_metadata = {
                    "artifact_type": "html_artifact",
                    "category": clean_type,
                    "title": final_title,
                    "prompt": clean_prompt,
                    "html": sanitized_html,
                    "css": sanitized_css,
                    "combined_preview": combined_preview,
                    "status": status_label,
                    "diagnostics": list(diagnostics),
                    "citations": [c.model_dump(mode="json") for c in citations],
                    "coverage": coverage.model_dump(mode="json") if coverage else None,
                    "disclaimer": disclaimer,
                    "provider": getattr(gen_res, "provider", self.settings.llm_provider) if "gen_res" in locals() else self.settings.llm_provider,
                    "model": getattr(gen_res, "model", self.settings.ollama_model) if "gen_res" in locals() else self.settings.ollama_model,
                }

                assistant_msg = create_message(
                    db=db,
                    session_id=session_id,
                    role="assistant",
                    content=f"Generated {clean_type.replace('_', ' ').title()} Artifact: {final_title}",
                    source_metadata=assistant_metadata,
                )
                message_id = assistant_msg.id
                is_persisted = True
            except Exception as e:
                if db is not None:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                logger.error("Failed to persist artifact in database: %s", e)
                diagnostics.append(f"Persistence error: Database save failed ({str(e)})")

        return ArtifactResponse(
            artifact_id=message_id,
            session_id=session_id,
            title=final_title,
            artifact_type=clean_type,
            prompt=clean_prompt,
            html=sanitized_html,
            css=sanitized_css,
            combined_preview=combined_preview,
            status=status_label,
            provider=active_provider,
            model=active_model,
            created_at=now,
            diagnostics=diagnostics,
            citations=citations,
            coverage=coverage,
            disclaimer=disclaimer,
            is_persisted=is_persisted,
        )

