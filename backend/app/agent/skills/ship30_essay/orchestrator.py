"""Ship 30 for 30 Essay Skill Orchestrator.

Coordinates semantic retrieval, bounded multi-stage generation via genuine Pi Coding Agent RPC,
word count validation, citation integrity, and PostgreSQL persistence.
"""

import asyncio
from datetime import datetime, timezone
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from fastapi import HTTPException, status
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
    EvidenceEntry,
    extract_cited_indices,
    prepare_bounded_evidence,
    validate_and_sanitize_citations,
)
from backend.app.agent.skills.ship30_essay.prompts import (
    build_outline_prompt,
    build_section_prompt,
    clean_section_markdown,
    count_words,
    format_essay_sources,
    is_duplicate_title,
    normalize_editorial_voice,
    reconcile_and_sanitize_essay_citations,
    split_sentences_safely,
    strip_draft_artifacts,
    strip_metadata_leaks,
    trim_section_to_budget,
    verify_essay_grounding,
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
from backend.app.schemas.essay import (
    EssayOutline,
    EssayResponse,
    EssaySectionPlan,
)

logger = logging.getLogger(__name__)

DEFAULT_AUDIENCE = "Product leaders and startup founders"
TARGET_ESSAY_WORDS = 1250
MIN_ACCEPTABLE_WORDS = 1100
MAX_ACCEPTABLE_WORDS = 1400


def compute_section_budget(
    section_index: int,
    total_sections: int,
    target_total_words: int = TARGET_ESSAY_WORDS,
) -> Tuple[int, int]:
    """Compute (target_words, max_words) for a given section index.

    Allocates slightly more budget to core analytical/tactical sections and
    tighter bounds to intro/conclusion, ensuring the sum lands near target (~1250)
    and strictly within [1100, 1400].
    """
    is_intro = section_index == 1
    is_conclusion = section_index == total_sections

    if total_sections == 5:
        if is_intro:
            return 230, 260
        elif is_conclusion:
            return 240, 270
        else:
            return 260, 285

    base_target = max(180, target_total_words // total_sections)
    if is_intro or is_conclusion:
        target = int(base_target * 0.92)
        max_words = int(target * 1.15)
    else:
        target = int(base_target * 1.05)
        max_words = int(target * 1.12)
    return target, max_words


def generate_natural_headline(topic: str, audience: str) -> str:
    """Generate a concise, specific and natural headline from topic and audience.

    Avoids robotic prefixes like 'The Operator's Playbook: <raw question>'.
    """
    clean = topic.strip().rstrip("?.")
    # Clean question prefixes like "What can ... learn about X from Y"
    m_learn = re.match(
        r"^(?:What\s+(?:can|should|do)\s+.*?\s+learn\s+about\s+(.+?)\s+from\s+(.+))$",
        clean,
        re.IGNORECASE,
    )
    if m_learn:
        subject = m_learn.group(1).strip()
        guest = m_learn.group(2).strip()
        return f"{subject.title()}: {guest}'s Lessons for {audience}"

    m_how = re.match(r"^How\s+(?:can|should|do)\s+(.+)$", clean, re.IGNORECASE)
    if m_how:
        return f"How to {m_how.group(1).strip().capitalize()}"

    m_when = re.match(r"^When\s+(?:should|to)\s+(.+)$", clean, re.IGNORECASE)
    if m_when:
        return f"When to {m_when.group(1).strip().capitalize()}"

    # General clean headline
    return f"{clean}: Operational Guide for {audience}"


class Ship30EssayOrchestrator:
    """Multi-stage orchestrator for generating grounded Ship 30 for 30 essays using Pi RPC."""

    def __init__(
        self,
        pi_client: Optional[PiClient] = None,
        retrieval_service: Optional[SemanticRetrievalService] = None,
        settings: Optional[Settings] = None,
        outline_timeout_seconds: Optional[int] = None,
        section_timeout_seconds: Optional[int] = None,
        total_timeout_seconds: Optional[int] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.pi_client = pi_client or PiClient(settings=self.settings)
        self.retrieval_service = retrieval_service
        self.outline_timeout = (
            outline_timeout_seconds
            if outline_timeout_seconds is not None
            else getattr(self.settings, "essay_outline_timeout_seconds", 180)
        )
        self.section_timeout = (
            section_timeout_seconds
            if section_timeout_seconds is not None
            else getattr(self.settings, "essay_section_timeout_seconds", 180)
        )
        self.total_timeout = (
            total_timeout_seconds
            if total_timeout_seconds is not None
            else getattr(self.settings, "essay_total_timeout_seconds", 900)
        )

    def _parse_outline_response(
        self,
        outline_text: str,
        topic: str,
        audience: str,
    ) -> Tuple[str, str, List[Tuple[str, str]]]:
        """Parse the outline generated by Pi in Stage 1 into Title, Thesis, and Section list."""
        title = ""
        thesis = ""
        sections: List[Tuple[str, str]] = []

        lines = outline_text.splitlines()
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # Robust matching supporting markdown bold (**TITLE:**), headers (### TITLE:), bullets (- TITLE:)
            title_match = re.match(
                r"^(?:[#*>\-\d.]+\s*)?(?:\*\*)?(?:TITLE|HEADLINE)(?:\*\*)?\s*[:\-]\s*(.+)$",
                line_str,
                re.IGNORECASE,
            )
            if title_match and not title:
                raw_title = title_match.group(1).strip()
                title = re.sub(r"^[*_`\"'#\s]+|[*_`\"'#\s]+$", "", raw_title).strip()
                continue

            thesis_match = re.match(
                r"^(?:[#*>\-\d.]+\s*)?(?:\*\*)?THESIS(?:\*\*)?\s*[:\-]\s*(.+)$",
                line_str,
                re.IGNORECASE,
            )
            if thesis_match and not thesis:
                raw_thesis = thesis_match.group(1).strip()
                thesis = re.sub(r"^[*_`\"'#\s]+|[*_`\"'#\s]+$", "", raw_thesis).strip()
                continue

            section_match = re.match(
                r"^(?:[#*>\-\d.]+\s*)?(?:\*\*)?SECTION\s*\d*(?:\*\*)?\s*[:\-]\s*(.+)$",
                line_str,
                re.IGNORECASE,
            )
            if section_match:
                content = section_match.group(1).strip()
                content = re.sub(r"^[*_`\"'#\s]+|[*_`\"'#\s]+$", "", content).strip()
                parts = content.split("|")
                heading = re.sub(r"^[*_`\"'#\s]+|[*_`\"'#\s]+$", "", parts[0]).strip()
                purpose = (
                    re.sub(r"^[*_`\"'#\s]+|[*_`\"'#\s]+$", "", parts[1].replace("PURPOSE:", "")).strip()
                    if len(parts) > 1
                    else heading
                )
                if heading:
                    sections.append((heading, purpose))
                continue

        # Fallback defaults if outline extraction is incomplete
        if not title:
            title = generate_natural_headline(topic, audience)

        # Sanitize section headings so none duplicate the essay title
        sanitized_sections = []
        for s_idx, (s_heading, s_purpose) in enumerate(sections):
            if is_duplicate_title(s_heading, title):
                if s_idx == 0:
                    s_heading = "The Core Tension & Strategic Dilemma"
                else:
                    s_heading = f"Key Strategic Principles (Part {s_idx + 1})"
            sanitized_sections.append((s_heading, s_purpose))
        sections = sanitized_sections

        if len(sections) < 4:
            clean_topic = topic.strip().rstrip("?.")
            sections = [
                (f"The Core Challenge in {clean_topic}", f"Establish the core context, tension, and thesis regarding {clean_topic}."),
                (f"First Principles & Strategic Thresholds", f"Detail concrete operational criteria, metrics, and foundations for {clean_topic}."),
                (f"The Tactical Execution Playbook", f"Provide step-by-step implementation rules and concrete mechanisms for {clean_topic}."),
                (f"Counter-Intuitive Traps & Common Failures", f"Analyze failure modes, premature shortcuts, and pitfalls in {clean_topic}."),
                (f"Actionable Synthesis & Key Takeaways", f"Actionable synthesis and definitive closing takeaway regarding {clean_topic}."),
            ]

        return title, thesis, sections

    async def generate_essay(
        self,
        session_id: uuid.UUID,
        topic: str,
        audience: Optional[str] = None,
        target_word_count: int = TARGET_ESSAY_WORDS,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        db: Session = ...,
    ) -> EssayResponse:
        """Execute the bounded 3-stage generation workflow to produce a ~1,250-word grounded essay."""
        target_audience = audience.strip() if audience and audience.strip() else DEFAULT_AUDIENCE
        now = datetime.now(timezone.utc)

        # 1. Validate session existence in PostgreSQL
        session = get_session_by_id(db=db, session_id=session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session with ID '{session_id}' not found.",
            )

        provider = (provider or self.settings.llm_provider or "ollama").strip().lower()
        if provider in ("google", "gemini"):
            provider = "google"
            model = model or getattr(self.settings, "gemini_model", "gemini-2.5-flash")
        elif provider == "ollama":
            model = model or self.settings.ollama_model or "qwen2.5:1.5b"
        elif provider == "openai":
            model = model or getattr(self.settings, "openai_model", "gpt-4o-mini")
        else:
            model = model or getattr(self.settings, "anthropic_model", "claude-3-5-sonnet-20241022")


        # 2. Retrieve grounded transcript passages
        retrieval_svc = self.retrieval_service or SemanticRetrievalService(db=db)
        try:
            retrieval_res = retrieval_svc.retrieve(
                query=f"{topic} {target_audience}",
                top_k=getattr(self.settings, "rag_top_k", 5),
            )
        except EmbeddingError as e:
            logger.error("Embedding generation failed for essay retrieval: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "embedding_unavailable",
                    "message": f"Query embedding service unavailable: {e}",
                    "retryable": True,
                },
            )
        except Exception as e:
            logger.error("Semantic retrieval failed for essay: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "retrieval_error",
                    "message": f"Semantic retrieval failed: {e}",
                    "retryable": True,
                },
            )

        # Honest grounding check: check for zero passages or no indexed content
        if not retrieval_res.items or retrieval_res.status in ("no_indexed_content", "insufficient_evidence"):
            warning_msg = (
                f"# Insufficient Transcript Evidence for Topic: {topic}\n\n"
                "> ⚠️ **Grounded Generation Notice**: Lenny's Podcast index does not contain "
                "sufficient verified transcript passages covering this topic. "
                "To prevent ungrounded AI hallucinations, essay generation was safely halted.\n\n"
                f"**Corpus Status:** {retrieval_res.disclaimer or 'Vector search returned no matching passages.'}"
            )
            # Record notification in conversation history
            assistant_msg = create_message(
                db=db,
                session_id=session_id,
                role="assistant",
                content=warning_msg,
                source_metadata={
                    "artifact_type": "ship30_essay",
                    "status": "insufficient_evidence",
                    "title": f"Insufficient Transcript Evidence: {topic}",
                    "topic": topic,
                    "audience": target_audience,
                    "word_count": count_words(warning_msg),
                    "target_word_count": target_word_count,
                    "citations": [],
                    "coverage": retrieval_res.coverage.model_dump() if retrieval_res.coverage else None,
                    "disclaimer": retrieval_res.disclaimer,
                },
            )
            return EssayResponse(
                session_id=session_id,
                message_id=assistant_msg.id,
                artifact_type="ship30_essay",
                title=f"Insufficient Transcript Evidence: {topic}",
                topic=topic,
                audience=target_audience,
                content=warning_msg,
                word_count=count_words(warning_msg),
                target_word_count=target_word_count,
                status="insufficient_evidence",
                provider=provider,
                model=model,
                citations=[],
                coverage=retrieval_res.coverage,
                disclaimer=retrieval_res.disclaimer,
                created_at=assistant_msg.created_at,
            )

        # Prepare bounded evidence entries
        evidence_entries = prepare_bounded_evidence(
            sources=retrieval_res.items,
            query=topic,
            max_passages=4,
            max_chars_per_passage=600,
            max_total_chars=2400,
        )

        episode_titles = [
            getattr(entry.source, "episode_title", "")
            for entry in evidence_entries
            if hasattr(entry, "source") and entry.source and getattr(entry.source, "episode_title", "")
        ]

        start_time = asyncio.get_running_loop().time()

        def remaining_budget() -> float:
            elapsed = asyncio.get_running_loop().time() - start_time
            return max(0.0, float(self.total_timeout) - elapsed)

        if remaining_budget() <= 5.0:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail={
                    "error": "essay_timeout",
                    "stage": "outline",
                    "message": f"Overall essay execution budget of {self.total_timeout}s exhausted before outline generation.",
                    "retryable": True,
                },
            )

        effective_outline_timeout = min(float(self.outline_timeout), remaining_budget())

        # -------------------------------------------------------------------
        # Stage 1 — Generate Structured Outline
        # -------------------------------------------------------------------
        logger.info(
            "Executing Ship 30 Stage 1: Outline generation (timeout=%ds)",
            int(effective_outline_timeout),
        )
        outline_prompt = build_outline_prompt(
            topic=topic,
            audience=target_audience,
            evidence_entries=evidence_entries,
        )

        try:
            outline_result = await self.pi_client.generate_response(
                prompt=outline_prompt,
                provider=provider,
                model=model,
                timeout_seconds=int(effective_outline_timeout),
            )
        except (PiAuthenticationError, PiConfigurationError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "pi_configuration_error", "stage": "outline", "message": str(e), "retryable": False},
            )
        except PiRateLimitError as e:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": "pi_rate_limit", "stage": "outline", "message": str(e), "retryable": True},
            )
        except (PiModelNotFoundError, PiNetworkError, PiProviderError) as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": "pi_provider_error", "stage": "outline", "message": str(e), "retryable": True},
            )
        except PiNotInstalledError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "pi_not_installed", "message": str(e), "retryable": True},
            )

        except PiTimeoutError as e:
            logger.error("Stage 1 Outline timed out after %s seconds: %s", int(effective_outline_timeout), e)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail={"error": "pi_timeout", "stage": "outline", "message": f"Stage 1 Outline timed out: {e}", "retryable": True},
            )
        except (PiPromptRejectedError, PiProcessTerminatedError, PiEmptyResponseError, PiAgentException) as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": "pi_runtime_error", "stage": "outline", "message": f"Stage 1 Outline generation failed: {e}", "retryable": True},
            )

        essay_title, core_thesis, section_plans = self._parse_outline_response(
            outline_text=outline_result.text,
            topic=topic,
            audience=target_audience,
        )

        # -------------------------------------------------------------------
        # Stage 2 — Sequential Section Drafting (Word Budgets)
        # -------------------------------------------------------------------
        logger.info(
            "Executing Ship 30 Stage 2: Drafting %d sections with word budgets",
            len(section_plans),
        )
        total_sections = len(section_plans)
        drafted_sections: List[str] = []
        omitted_sections: List[Tuple[str, str, str]] = []  # (heading, purpose, reason)
        previous_summary: Optional[str] = None

        for idx, (heading, purpose) in enumerate(section_plans, start=1):
            target_budget, max_budget = compute_section_budget(
                section_index=idx,
                total_sections=total_sections,
                target_total_words=target_word_count,
            )

            if remaining_budget() <= 5.0:
                logger.warning(
                    "Overall essay budget exhausted (%ss remaining) before section %d ('%s'); omitting section to prevent placeholder fabrication",
                    round(remaining_budget(), 1),
                    idx,
                    heading,
                )
                omitted_sections.append((heading, purpose, "Execution time budget exhausted"))
                continue

            section_prompt = build_section_prompt(
                section_index=idx,
                total_sections=total_sections,
                heading=heading,
                purpose=purpose,
                target_words=target_budget,
                topic=topic,
                audience=target_audience,
                evidence_entries=evidence_entries,
                previous_summary=previous_summary,
            )

            # Attempt drafting with safe retry within available budget
            sec_text = ""
            last_error = ""
            max_attempts = 2 if remaining_budget() >= 25.0 else 1

            for attempt in range(1, max_attempts + 1):
                effective_section_timeout = min(float(self.section_timeout), remaining_budget() - 2.0)
                if effective_section_timeout < 4.0:
                    last_error = "Insufficient remaining execution budget"
                    break

                try:
                    sec_res = await self.pi_client.generate_response(
                        prompt=section_prompt,
                        provider=provider,
                        model=model,
                        timeout_seconds=int(effective_section_timeout),
                    )
                    sec_text = sec_res.text.strip()
                    if sec_text:
                        break
                except PiTimeoutError as e:
                    last_error = f"Timed out after {int(effective_section_timeout)}s"
                    logger.warning(
                        "Stage 2 section %d ('%s') attempt %d timed out: %s",
                        idx,
                        heading,
                        attempt,
                        e,
                    )
                except Exception as e:
                    last_error = str(e)
                    logger.warning(
                        "Stage 2 section %d ('%s') attempt %d failed: %s",
                        idx,
                        heading,
                        attempt,
                        e,
                    )

            if sec_text:
                cleaned_sec = clean_section_markdown(
                    text=sec_text,
                    is_intro=(idx == 1),
                    essay_title=essay_title,
                    known_episode_titles=episode_titles,
                )
                trimmed_sec = trim_section_to_budget(
                    section_markdown=cleaned_sec,
                    target_words=target_budget,
                    max_words=max_budget,
                    is_intro=(idx == 1),
                    is_conclusion=(idx == total_sections),
                )
                trimmed_sec, _ = strip_draft_artifacts(trimmed_sec)
                drafted_sections.append(trimmed_sec)
                previous_summary = f"Section {idx} ('{heading}'): {trimmed_sec[:200]}..."
            else:
                logger.warning(
                    "Stage 2 section %d ('%s') drafting failed (%s); omitting section to preserve factual integrity",
                    idx,
                    heading,
                    last_error,
                )
                omitted_sections.append((heading, purpose, last_error or "Section generation failed"))

        # -------------------------------------------------------------------
        # Stage 3 — Assemble and Validate Full Essay
        # -------------------------------------------------------------------
        logger.info("Executing Ship 30 Stage 3: Assembling and validating essay")

        # Normalize and clean all drafted sections
        cleaned_sections = []
        for sec in drafted_sections:
            c = clean_section_markdown(
                text=sec,
                is_intro=False,
                essay_title=essay_title,
                known_episode_titles=episode_titles,
            )
            if c.strip():
                cleaned_sections.append(c.strip())

        body_content = "\n\n".join(cleaned_sections)
        assembled_markdown = f"# {essay_title}\n\n{body_content}"

        # Clean assembled markdown with essay_title provided to guarantee deduplication and single H1
        assembled_markdown = clean_section_markdown(
            text=assembled_markdown,
            is_intro=False,
            essay_title=essay_title,
            known_episode_titles=episode_titles,
        )
        if not assembled_markdown.startswith("# "):
            assembled_markdown = f"# {essay_title}\n\n{assembled_markdown}"

        # Strip draft artifacts, author scaffolding, and instructions
        assembled_markdown, draft_artifacts = strip_draft_artifacts(assembled_markdown)

        # Reconcile inline citations against verified evidence entries (strip unsupported markers like [5])
        assembled_markdown, valid_cited, invalid_cited = reconcile_and_sanitize_essay_citations(
            text=assembled_markdown,
            evidence_entries=evidence_entries,
        )

        # Deduplicate any H2 heading that duplicates the title immediately following H1
        lines = assembled_markdown.splitlines()
        processed_lines = []
        for line in lines:
            if line.startswith("## "):
                h2_text = line[3:].strip()
                if is_duplicate_title(h2_text, essay_title):
                    if len(processed_lines) <= 2:
                        processed_lines.append("## The Core Tension & Strategic Dilemma")
                    continue
            processed_lines.append(line)
        assembled_markdown = "\n".join(processed_lines)

        # Measure accurate body word count (excluding Sources block metadata/URLs)
        final_word_count = count_words(assembled_markdown)

        # Append terminal Sources block with clickable YouTube timestamps (strictly verified sources)
        sources_block = format_essay_sources(evidence_entries, valid_cited)
        full_essay_content = (assembled_markdown + sources_block) if sources_block else assembled_markdown

        # Grounding validation against retrieved evidence
        grounding_audit = verify_essay_grounding(
            text=assembled_markdown,
            evidence_entries=evidence_entries,
            topic=topic,
        )
        has_grounding_defects = not grounding_audit["is_grounded"]

        # Structural, draft-artifact, and grounding checks for honest completion status
        h1_matches = re.findall(r"^#\s+[^#]", assembled_markdown, flags=re.MULTILINE)
        h2_headings = re.findall(r"^##\s+(.+)$", assembled_markdown, flags=re.MULTILINE)
        has_duplicate_h2 = any(is_duplicate_title(h2, essay_title) for h2 in h2_headings)
        has_draft_artifacts = len(draft_artifacts) > 0
        has_unresolved_citations = len(invalid_cited) > 0
        has_code_fences = "```markdown" in assembled_markdown.lower() or assembled_markdown.strip().startswith("```")

        has_valid_structure = (
            len(h1_matches) == 1
            and not has_code_fences
            and not has_duplicate_h2
            and not has_draft_artifacts
            and not has_unresolved_citations
            and not has_grounding_defects
            and len(omitted_sections) == 0
            and len(cleaned_sections) == total_sections
            and len(valid_cited) >= 1
        )

        if MIN_ACCEPTABLE_WORDS <= final_word_count <= MAX_ACCEPTABLE_WORDS and has_valid_structure:
            status_label = "completed"
        else:
            status_label = "partial"

        # Construct comprehensive advisory disclaimer if partial or grounding issues exist
        disclaimer_parts = []
        if retrieval_res.disclaimer:
            disclaimer_parts.append(retrieval_res.disclaimer)
        if omitted_sections:
            omitted_names = ", ".join(f"'{h}'" for h, _, _ in omitted_sections)
            disclaimer_parts.append(
                f"Partial Draft Notice: {len(omitted_sections)} planned section(s) ({omitted_names}) could not be completed within the execution budget and were omitted to preserve factual grounding."
            )
        if final_word_count < MIN_ACCEPTABLE_WORDS:
            disclaimer_parts.append(
                f"Length Notice: The generated draft is {final_word_count} words (target: {MIN_ACCEPTABLE_WORDS}–{MAX_ACCEPTABLE_WORDS} words) to avoid ungrounded padding beyond verified podcast transcripts."
            )
        if has_grounding_defects:
            diag_summary = "; ".join(grounding_audit["diagnostics"])
            disclaimer_parts.append(
                f"Grounding Advisory: Potential unverified assertions detected ({diag_summary}). Editorial review recommended."
            )
        effective_disclaimer = " ".join(disclaimer_parts) if disclaimer_parts else None

        # Validate structured citations for API response and persistence (strictly verified sources)
        index_to_source = {entry.index: entry.source for entry in evidence_entries}
        validated_citations = [index_to_source[idx] for idx in valid_cited if idx in index_to_source]

        # -------------------------------------------------------------------
        # Step 4: Persist in PostgreSQL
        # -------------------------------------------------------------------
        # 1. User turn message
        user_msg = create_message(
            db=db,
            session_id=session_id,
            role="user",
            content=f"Write a Ship 30 for 30 essay on: {topic} (Audience: {target_audience})",
            source_metadata=None,
        )

        # 2. Assistant essay artifact message
        essay_metadata = {
            "artifact_type": "ship30_essay",
            "title": essay_title,
            "topic": topic,
            "audience": target_audience,
            "word_count": final_word_count,
            "target_word_count": target_word_count,
            "status": status_label,
            "provider": provider,
            "model": model,
            "citations": [c.model_dump(mode="json") for c in validated_citations],
            "coverage": retrieval_res.coverage.model_dump() if retrieval_res.coverage else None,
            "disclaimer": effective_disclaimer,
            "unresolved_citations": invalid_cited,
            "draft_artifacts_detected": draft_artifacts,
            "grounding_audit": grounding_audit,
        }
        assistant_msg = create_message(
            db=db,
            session_id=session_id,
            role="assistant",
            content=full_essay_content,
            source_metadata=essay_metadata,
        )

        return EssayResponse(
            session_id=session_id,
            message_id=assistant_msg.id,
            artifact_type="ship30_essay",
            title=essay_title,
            topic=topic,
            audience=target_audience,
            content=full_essay_content,
            word_count=final_word_count,
            target_word_count=target_word_count,
            status=status_label,
            provider=provider,
            model=model,
            citations=validated_citations,
            coverage=retrieval_res.coverage,
            disclaimer=effective_disclaimer,
            created_at=assistant_msg.created_at,
        )
