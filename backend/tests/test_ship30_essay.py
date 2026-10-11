"""Unit and integration tests for Ship 30 for 30 essay skill backend implementation (Phase 5A)."""

import asyncio
from datetime import datetime, timezone
import re
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.agent.exceptions import (
    PiAgentException,
    PiNotInstalledError,
    PiTimeoutError,
)
from backend.app.agent.pi_client import PiClient, PiGenerationResult
from backend.app.agent.rag import EvidenceEntry, prepare_bounded_evidence
from backend.app.agent.skills.ship30_essay import (
    DEFAULT_AUDIENCE,
    MAX_ACCEPTABLE_WORDS,
    MIN_ACCEPTABLE_WORDS,
    TARGET_ESSAY_WORDS,
    Ship30EssayOrchestrator,
    build_outline_prompt,
    build_section_prompt,
    clean_section_markdown,
    compute_section_budget,
    count_words,
    format_essay_sources,
    generate_natural_headline,
    is_duplicate_title,
    load_skill_instructions,
    normalize_editorial_voice,
    reconcile_and_sanitize_essay_citations,
    split_sentences_safely,
    strip_draft_artifacts,
    strip_metadata_leaks,
    trim_section_to_budget,
    extract_evidence_corpus,
    verify_essay_grounding,
)
from backend.app.models.message import ChatMessage
from backend.app.models.session import ChatSession
from backend.app.repositories import create_session, list_messages_by_session
from backend.app.retrieval.schemas import (
    CitationSource,
    IndexCoverage,
    RetrievalResponse,
)
from backend.app.retrieval.service import SemanticRetrievalService
from backend.app.schemas.essay import (
    EssayGenerateRequest,
    EssayResponse,
)


def _mock_citation(
    title: str = "When to Hire Sales",
    guest: str = "Jason Lemkin",
    start_seconds: float = 135.0,
    content: str = "Founders should close their first 10 customers themselves before hiring sales reps.",
) -> CitationSource:
    """Helper to create a realistic mock CitationSource."""
    ep_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    return CitationSource(
        episode_id=ep_id,
        episode_title=title,
        episode_slug="jason-lemkin",
        guest_name=guest,
        chunk_id=chunk_id,
        chunk_index=0,
        content=content,
        char_start=0,
        char_end=len(content),
        start_seconds=start_seconds,
        end_seconds=start_seconds + 30.0,
        timestamp_label="02:15",
        youtube_url="https://www.youtube.com/watch?v=mock_video",
        timestamped_url=f"https://www.youtube.com/watch?v=mock_video&t={int(start_seconds)}s",
        cosine_distance=0.15,
        similarity_score=0.85,
    )


def _mock_coverage() -> IndexCoverage:
    """Helper to create realistic mock IndexCoverage."""
    return IndexCoverage(
        total_episodes=303,
        indexed_episodes=3,
        total_chunks=20369,
        indexed_chunks=200,
        model_name="nomic-embed-text",
        is_partial=True,
        description="Index covers 3 of 303 episodes.",
    )


# ---------------------------------------------------------------------------
# Unit tests: Skill Instructions & Formatting
# ---------------------------------------------------------------------------

def test_skill_md_loads_and_has_required_sections():
    """Verify that SKILL.md exists, loads successfully, and contains key writing principles."""
    instructions = load_skill_instructions()
    assert len(instructions) > 200
    assert "Ship 30 for 30" in instructions
    assert "Clear Over Clever Headlines" in instructions
    assert "1,250" in instructions
    assert "Grounding" in instructions or "grounded" in instructions.lower()


def test_count_words_accuracy():
    """Verify that count_words accurately measures word count excluding code blocks and HTML tags."""
    sample = "This is a simple seven word sentence."
    assert count_words(sample) == 7

    markdown_sample = """# Title

This paragraph contains eight words in plain text.

```python
# Code block should not count as body words
x = 100
print(x)
```

And three more words.
"""
    # "# Title" (2) + "This paragraph contains eight words in plain text." (8) + "And three more words." (4) = 14
    assert count_words(markdown_sample) == 14
    assert count_words("") == 0
    assert count_words("   ") == 0


def test_essay_request_validation():
    """Verify that EssayGenerateRequest validates non-empty topics and normalizes input."""
    valid_req = EssayGenerateRequest(
        topic="When to hire your first salesperson",
        audience="Early-stage SaaS founders",
    )
    assert valid_req.topic == "When to hire your first salesperson"
    assert valid_req.audience == "Early-stage SaaS founders"
    assert valid_req.target_word_count == 1250

    # Whitespace-only topic rejected
    with pytest.raises(ValueError):
        EssayGenerateRequest(topic="   ")

    # Short topic rejected
    with pytest.raises(ValueError):
        EssayGenerateRequest(topic="ab")


def test_outline_prompt_construction():
    """Verify that build_outline_prompt incorporates topic, audience, and evidence passages."""
    evidence = [
        EvidenceEntry(
            index=1,
            source=_mock_citation(content="Founders must close the first 10 customers themselves."),
            header="[1] Episode: \"When to Hire Sales\", Guest: Jason Lemkin, Time: 02:15",
            excerpt="Founders must close the first 10 customers themselves.",
        )
    ]
    prompt = build_outline_prompt(
        topic="Hiring first salespeople",
        audience="Early-stage founders",
        evidence_entries=evidence,
    )
    assert "Hiring first salespeople" in prompt
    assert "Early-stage founders" in prompt
    assert "[1]" in prompt
    assert "Jason Lemkin" in prompt
    assert "Ship 30 for 30" in prompt


def test_section_prompt_construction():
    """Verify that build_section_prompt sets word budget and Ship 30 pacing instructions."""
    evidence = [
        EvidenceEntry(
            index=1,
            source=_mock_citation(),
            header="[1] Episode: \"When to Hire Sales\", Guest: Jason Lemkin, Time: 02:15",
            excerpt="Close first 10 customers personally.",
        )
    ]
    prompt = build_section_prompt(
        section_index=2,
        total_sections=5,
        heading="The 10-Customer Rule",
        purpose="Explain why personal founder sales cannot be delegated early.",
        target_words=250,
        topic="Sales hiring timing",
        audience="SaaS founders",
        evidence_entries=evidence,
        previous_summary="Section 1 covered the founder trap.",
    )
    assert "Section 2 of 5" in prompt
    assert "The 10-Customer Rule" in prompt
    assert "250 words" in prompt
    assert "Section 1 covered the founder trap" in prompt
    assert "Varied Sentence Rhythm" in prompt


def test_format_essay_sources_youtube_links():
    """Verify that format_essay_sources generates markdown footnotes with timestamped URLs."""
    evidence = [
        EvidenceEntry(
            index=1,
            source=_mock_citation(title="Sales Strategy", guest="Jason Lemkin", start_seconds=135.0),
            header="[1] Episode: \"Sales Strategy\", Guest: Jason Lemkin, Time: 02:15",
            excerpt="Close first 10 customers yourself.",
        )
    ]
    sources_text = format_essay_sources(evidence, cited_indices=[1])
    assert "### Sources" in sources_text
    assert "[1] [Sales Strategy - Guest: Jason Lemkin [at 02:15]](https://www.youtube.com/watch?v=mock_video&t=135s)" in sources_text


# ---------------------------------------------------------------------------
# API & Orchestrator Integration Tests
# ---------------------------------------------------------------------------

def test_essay_generation_session_not_found(client: TestClient):
    """Verify that POST /api/sessions/{session_id}/essay returns 404 for non-existent session."""
    random_id = str(uuid.uuid4())
    payload = {"topic": "When to hire sales"}
    response = client.post(f"/api/sessions/{random_id}/essay", json=payload)
    assert response.status_code == 404
    assert f"'{random_id}' not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_insufficient_evidence_safeguard_halts_generation(db_session: Session):
    """Verify that orchestrator halts and returns an honest notice when no evidence is found."""
    session = create_session(db=db_session, title="Empty Session")
    mock_retrieval_svc = MagicMock(spec=SemanticRetrievalService)
    mock_retrieval_svc.retrieve.return_value = RetrievalResponse(
        query="unindexed topic",
        status="no_indexed_content",
        items=[],
        coverage=_mock_coverage(),
        disclaimer="No matching passages found in index.",
    )

    mock_pi = MagicMock(spec=PiClient)

    orchestrator = Ship30EssayOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval_svc,
    )

    result = await orchestrator.generate_essay(
        session_id=session.id,
        topic="Unindexed exotic topic",
        db=db_session,
    )

    assert result.status == "insufficient_evidence"
    assert "Insufficient Transcript Evidence" in result.title
    assert "safely halted" in result.content
    # Pi generation should NOT be called if evidence is insufficient
    mock_pi.generate_response.assert_not_called()


@pytest.mark.asyncio
async def test_multi_stage_orchestration_flow_success(db_session: Session):
    """Verify that the 3-stage orchestrator calls Pi for outline and sections and persists the essay."""
    session = create_session(db=db_session, title="Sales Discussion")
    mock_retrieval_svc = MagicMock(spec=SemanticRetrievalService)
    citation = _mock_citation()
    mock_retrieval_svc.retrieve.return_value = RetrievalResponse(
        query="sales hiring",
        status="success",
        items=[citation],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    # Mock Pi responses: 1 outline response + 5 section responses
    mock_outline_text = """TITLE: When Should Founders Hire Sales? The 10-Customer Rule
AUDIENCE: Early-Stage SaaS Founders
HOOK: Most founders hire sales reps too early and burn half their seed round.
THESIS: Never hire a salesperson until you have personally closed your first 10 customers.
SECTION 1: The Seductive Outsourcing Trap | PURPOSE: Explain the common misconception. | EVIDENCE: [1]
SECTION 2: The 10-Customer Threshold | PURPOSE: Detail the empirical customer threshold. | EVIDENCE: [1]
SECTION 3: The 20-Percent Rule | PURPOSE: The time allocation trigger point. | EVIDENCE: [1]
SECTION 4: The Two-Rep Rule | PURPOSE: Why you should always hire two reps instead of one. | EVIDENCE: [1]
SECTION 5: 30-Day Founder Action Plan | PURPOSE: Clear execution steps and conclusion. | EVIDENCE: [1]
TAKEAWAY: Close 10 customers yourself first.
"""

    # Generate substantive section text (~230 words per section) to reach target acceptance range (1,100–1,400 words)
    section_words = (
        "Founders often believe that hiring a salesperson will solve their revenue problems. "
        "However, early-stage selling is not sales execution; it is product discovery [1]. "
        "When you outsource sales prematurely, you sever the feedback loop between the market and product development. "
        "Every conversation with a prospect reveals pricing sensitivity, feature gaps, and positioning friction. "
        "A sales rep cannot adjust the product roadmap or alter the value proposition during a discovery call. "
        "Only a founder has the authority and context to pivot the messaging in real time. "
        "Jason Lemkin emphasizes that closing your first ten customers yourself is non-negotiable [1]. "
        "Until ten customers have signed contracts and paid real money, you do not have a repeatable playbook. "
        "Hiring before this milestone guarantees that you burn capital training reps on an unproven product. "
        "To succeed, keep sales in-house: **talk to customers directly**, document objections, and validate the pricing model. "
        "Documenting discovery feedback allows the founding team to refine the ideal customer profile rapidly. "
        "When founders handle the earliest sales pipeline personally, closing velocity accelerates and unit economics stabilize. "
        "Here are three rules every founder must follow before making their first sales hire:\n"
        "- Personally demo the software to at least thirty qualified prospects.\n"
        "- Close ten paying accounts without sales assistance.\n"
        "- Maintain an updated document of common objections and customer onboarding hurdles.\n\n"
        "Execution discipline separates breakout SaaS companies from those that stall out in the seed stage. "
        "Commit to doing the unscalable work until the sales loop is completely repeatable."
    )

    mock_pi = MagicMock(spec=PiClient)
    # Stage 1 return, followed by 5 section returns
    mock_pi.generate_response = AsyncMock(
        side_effect=[
            PiGenerationResult(text=mock_outline_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=section_words, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=section_words, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=section_words, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=section_words, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=section_words, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        ]
    )

    orchestrator = Ship30EssayOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval_svc,
    )

    result = await orchestrator.generate_essay(
        session_id=session.id,
        topic="When to hire sales according to Jason Lemkin",
        audience="Early-Stage SaaS Founders",
        db=db_session,
    )

    # Verification of multi-stage orchestration
    assert mock_pi.generate_response.call_count == 6
    assert result.session_id == session.id
    assert "When Should Founders Hire Sales?" in result.title
    assert result.word_count >= 1000
    assert result.status == "completed" or result.status == "partial"
    assert "### Sources" in result.content
    assert len(result.citations) >= 1

    # Verify stage-specific timeout propagation to PiClient
    assert mock_pi.generate_response.call_args_list[0].kwargs["timeout_seconds"] == 180
    assert mock_pi.generate_response.call_args_list[1].kwargs["timeout_seconds"] == 180

    # Verify message persistence in PostgreSQL
    messages, total = list_messages_by_session(db=db_session, session_id=session.id)
    assert total == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    assert messages[1].source_metadata["artifact_type"] == "ship30_essay"
    assert messages[1].source_metadata["title"] == result.title


def test_api_post_and_get_essay_endpoints(client: TestClient, db_session: Session):
    """Verify that POST /api/sessions/{id}/essay and GET /api/sessions/{id}/essay integrate properly."""
    # 1. Create a session
    sess_res = client.post("/api/sessions", json={"title": "Podcast Discussion"})
    assert sess_res.status_code == 201
    session_id = sess_res.json()["id"]

    # 2. Supply controlled realistic retrieval evidence and mock Pi responses
    mock_retrieval_res = RetrievalResponse(
        query="Sales hiring timing Early-stage founders",
        status="success",
        items=[_mock_citation(title="When to Hire Sales", guest="Jason Lemkin", content="Founders must close the first 10 customers themselves.")],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    mock_outline_text = (
        "TITLE: When to Hire Sales: The Definitive SaaS Guide\n"
        "AUDIENCE: Early-stage founders\n"
        "HOOK: Most founders hire sales reps too early and burn half their seed round.\n"
        "THESIS: Never hire a salesperson until you have personally closed your first 10 customers.\n"
        "SECTION 1: The Seductive Outsourcing Trap | PURPOSE: Explain the common misconception. | EVIDENCE: [1]\n"
        "SECTION 2: The 10-Customer Threshold | PURPOSE: Detail the customer threshold. | EVIDENCE: [1]\n"
        "SECTION 3: The 20-Percent Rule | PURPOSE: The time allocation trigger point. | EVIDENCE: [1]\n"
        "SECTION 4: The Two-Rep Rule | PURPOSE: Why you should hire two reps. | EVIDENCE: [1]\n"
        "SECTION 5: 30-Day Founder Action Plan | PURPOSE: Clear execution steps. | EVIDENCE: [1]\n"
        "TAKEAWAY: Close 10 customers yourself first.\n"
    )

    section_words = (
        "Founders often believe that hiring a salesperson will solve their revenue problems. "
        "However, early-stage selling is not sales execution; it is product discovery [1]. "
        "When you outsource sales prematurely, you sever the feedback loop between the market and product development. "
        "Every conversation with a prospect reveals pricing sensitivity, feature gaps, and positioning friction. "
        "A sales rep cannot adjust the product roadmap or alter the value proposition during a discovery call. "
        "Only a founder has the authority and context to pivot the messaging in real time. "
        "Jason Lemkin emphasizes that closing your first ten customers yourself is non-negotiable [1]. "
        "Until ten customers have signed contracts and paid real money, you do not have a repeatable playbook. "
        "Hiring before this milestone guarantees that you burn capital training reps on an unproven product. "
        "To succeed, keep sales in-house: **talk to customers directly**, document objections, and validate the pricing model. "
        "Documenting discovery feedback allows the founding team to refine the ideal customer profile rapidly. "
        "When founders handle the earliest sales pipeline personally, closing velocity accelerates and unit economics stabilize. "
        "Here are three rules every founder must follow before making their first sales hire:\n"
        "- Personally demo the software to at least thirty qualified prospects.\n"
        "- Close ten paying accounts without sales assistance.\n"
        "- Maintain an updated document of common objections and customer onboarding hurdles.\n\n"
        "Execution discipline separates breakout SaaS companies from those that stall out in the seed stage. "
        "Commit to doing the unscalable work until the sales loop is completely repeatable."
    )

    pi_side_effects = [
        PiGenerationResult(text=mock_outline_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        PiGenerationResult(text=section_words, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        PiGenerationResult(text=section_words, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        PiGenerationResult(text=section_words, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        PiGenerationResult(text=section_words, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        PiGenerationResult(text=section_words, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
    ]

    with patch.object(SemanticRetrievalService, "retrieve", return_value=mock_retrieval_res), \
         patch.object(PiClient, "generate_response", AsyncMock(side_effect=pi_side_effects)):

        post_res = client.post(
            f"/api/sessions/{session_id}/essay",
            json={"topic": "Sales hiring timing", "audience": "Early-stage founders"},
        )
        assert post_res.status_code == 201
        data = post_res.json()
        assert data["title"] == "When to Hire Sales: The Definitive SaaS Guide"
        assert data["word_count"] >= 1000
        assert data["artifact_type"] == "ship30_essay"
        assert data["status"] in ("completed", "partial")
        assert "### Sources" in data["content"]
        assert len(data["citations"]) >= 1

        # 3. Verify GET retrieves the previously generated essay artifact
        get_res = client.get(f"/api/sessions/{session_id}/essay")
        assert get_res.status_code == 200
        get_data = get_res.json()
        assert get_data["title"] == data["title"]
        assert get_data["content"] == data["content"]
        assert get_data["word_count"] == data["word_count"]
        assert get_data["artifact_type"] == "ship30_essay"
        assert get_data["session_id"] == session_id


def test_get_essay_not_found_when_no_essay(client: TestClient):
    """Verify that GET /api/sessions/{id}/essay returns 404 when no essay has been generated."""
    sess_res = client.post("/api/sessions", json={"title": "Empty Chat"})
    session_id = sess_res.json()["id"]

    get_res = client.get(f"/api/sessions/{session_id}/essay")
    assert get_res.status_code == 404
    assert "No generated essay artifact found" in get_res.json()["detail"]


@pytest.mark.asyncio
async def test_pi_timeout_error_handling(db_session: Session):
    """Verify that a Pi timeout during outline generation raises HTTP 504."""
    session = create_session(db=db_session, title="Timeout Test")
    mock_retrieval_svc = MagicMock(spec=SemanticRetrievalService)
    mock_retrieval_svc.retrieve.return_value = RetrievalResponse(
        query="timeout query",
        status="success",
        items=[_mock_citation()],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(side_effect=PiTimeoutError("Pi RPC generation timed out"))

    orchestrator = Ship30EssayOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval_svc,
    )

    with pytest.raises(HTTPException) as exc_info:
        await orchestrator.generate_essay(
            session_id=session.id,
            topic="Sales hiring timing",
            db=db_session,
        )
    assert exc_info.value.status_code == 504
    assert exc_info.value.detail["error"] == "pi_timeout"
    assert exc_info.value.detail["stage"] == "outline"

    # Verify no corrupt or misleading message was persisted following failure
    messages, total = list_messages_by_session(db=db_session, session_id=session.id)
    assert total == 0


@pytest.mark.asyncio
async def test_pi_runtime_error_handling(db_session: Session):
    """Verify that a Pi runtime failure during outline generation raises HTTP 502."""
    session = create_session(db=db_session, title="Runtime Error Test")
    mock_retrieval_svc = MagicMock(spec=SemanticRetrievalService)
    mock_retrieval_svc.retrieve.return_value = RetrievalResponse(
        query="runtime error query",
        status="success",
        items=[_mock_citation()],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(side_effect=PiAgentException("Pi process terminated unexpectedly"))

    orchestrator = Ship30EssayOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval_svc,
    )

    with pytest.raises(HTTPException) as exc_info:
        await orchestrator.generate_essay(
            session_id=session.id,
            topic="Sales hiring timing",
            db=db_session,
        )
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error"] == "pi_runtime_error"


@pytest.mark.asyncio
async def test_section_timeout_produces_partial_essay_safely(db_session: Session):
    """Verify that a Pi timeout during section drafting applies fallback and reports 'partial'."""
    session = create_session(db=db_session, title="Section Timeout Session")
    mock_retrieval_svc = MagicMock(spec=SemanticRetrievalService)
    mock_retrieval_svc.retrieve.return_value = RetrievalResponse(
        query="sales hiring",
        status="success",
        items=[_mock_citation()],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    mock_outline_text = (
        "TITLE: Founder Sales Playbook\n"
        "AUDIENCE: SaaS Founders\n"
        "HOOK: Most founders delegate sales too early.\n"
        "THESIS: Close 10 customers yourself first.\n"
        "SECTION 1: Foundational Principle | PURPOSE: The 10-customer rule | EVIDENCE: [1]\n"
        "SECTION 2: Execution Mechanics | PURPOSE: Step-by-step discovery | EVIDENCE: [1]\n"
        "SECTION 3: Dangerous Traps | PURPOSE: Premature rep hiring | EVIDENCE: [1]\n"
        "SECTION 4: Action Framework | PURPOSE: 30-day plan | EVIDENCE: [1]\n"
        "TAKEAWAY: Close 10 customers yourself first.\n"
    )

    mock_pi = MagicMock(spec=PiClient)
    # Stage 1 succeeds, first section succeeds with grounded evidence, remaining sections time out
    mock_pi.generate_response = AsyncMock(
        side_effect=[
            PiGenerationResult(text=mock_outline_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text="## Foundational Principle\n\nClose 10 customers yourself first [1]. This ensures direct learning from customer feedback.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiTimeoutError("Section 2 generation timed out after 180 seconds"),
            PiTimeoutError("Section 3 generation timed out after 180 seconds"),
            PiTimeoutError("Section 4 generation timed out after 180 seconds"),
        ]
    )

    orchestrator = Ship30EssayOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval_svc,
        outline_timeout_seconds=180,
        section_timeout_seconds=180,
    )

    result = await orchestrator.generate_essay(
        session_id=session.id,
        topic="Sales hiring timing",
        db=db_session,
    )

    # Must complete safely as 'partial' (never claimed as 'completed')
    assert result.status == "partial"
    assert result.session_id == session.id
    assert "Founder Sales Playbook" in result.title
    assert "### Sources" in result.content
    assert "The 10-customer rule" not in result.content  # Purpose planning string never exposed
    assert "execution rigor and validated milestones" not in result.content  # No fabricated generic assertions
    assert result.disclaimer is not None and "Partial Draft Notice" in result.disclaimer

    # Persistence verification: assistant message is stored with status 'partial'
    messages, total = list_messages_by_session(db=db_session, session_id=session.id)
    assert total == 2
    assert messages[1].source_metadata["status"] == "partial"


@pytest.mark.asyncio
async def test_overall_essay_budget_exhaustion_raises_504(db_session: Session):
    """Verify that overall essay execution budget bound triggers HTTP 504 when exhausted."""
    session = create_session(db=db_session, title="Budget Test")
    mock_retrieval_svc = MagicMock(spec=SemanticRetrievalService)
    mock_retrieval_svc.retrieve.return_value = RetrievalResponse(
        query="budget query",
        status="success",
        items=[_mock_citation()],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock()

    # Orchestrator configured with 0-second total budget (already expired)
    orchestrator = Ship30EssayOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval_svc,
        total_timeout_seconds=0,
    )

    with pytest.raises(HTTPException) as exc_info:
        await orchestrator.generate_essay(
            session_id=session.id,
            topic="Sales hiring timing",
            db=db_session,
        )
    assert exc_info.value.status_code == 504
    assert exc_info.value.detail["error"] == "essay_timeout"
    mock_pi.generate_response.assert_not_called()


@pytest.mark.asyncio
async def test_custom_stage_timeouts_propagate_to_pi_client(db_session: Session):
    """Verify that custom outline and section timeouts propagate to PiClient.generate_response."""
    session = create_session(db=db_session, title="Custom Timeout Session")
    mock_retrieval_svc = MagicMock(spec=SemanticRetrievalService)
    mock_retrieval_svc.retrieve.return_value = RetrievalResponse(
        query="sales hiring",
        status="success",
        items=[_mock_citation()],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    mock_outline_text = (
        "TITLE: Custom Timeout Essay\n"
        "AUDIENCE: SaaS Founders\n"
        "HOOK: Fast hook.\n"
        "THESIS: Strong thesis.\n"
        "SECTION 1: Part 1 | PURPOSE: P1 | EVIDENCE: [1]\n"
        "TAKEAWAY: Done.\n"
    )

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(
        side_effect=[
            PiGenerationResult(text=mock_outline_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text="Section content here.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text="Section content here.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text="Section content here.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text="Section content here.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text="Section content here.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        ]
    )

    orchestrator = Ship30EssayOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval_svc,
        outline_timeout_seconds=210,
        section_timeout_seconds=240,
        total_timeout_seconds=1200,
    )

    await orchestrator.generate_essay(
        session_id=session.id,
        topic="Sales hiring timing",
        db=db_session,
    )

    # Verify Stage 1 outline used 210s
    stage1_call = mock_pi.generate_response.call_args_list[0]
    assert stage1_call.kwargs["timeout_seconds"] == 210

    # Verify Stage 2 sections used 240s
    stage2_call = mock_pi.generate_response.call_args_list[1]
    assert stage2_call.kwargs["timeout_seconds"] == 240


def test_normal_chat_timeout_setting_unchanged():
    """Verify that ordinary chat PI_AGENT_TIMEOUT_SECONDS setting remains untouched at 120s."""
    from backend.app.config import Settings
    settings = Settings()
    assert settings.pi_agent_timeout_seconds == 120
    assert settings.essay_outline_timeout_seconds == 180
    assert settings.essay_section_timeout_seconds == 180
    assert settings.essay_total_timeout_seconds == 900


# ---------------------------------------------------------------------------
# Phase 5A Correction 5: Controlled Word Budgets & Structure-Aware Trimming
# ---------------------------------------------------------------------------

def test_section_budget_allocation_computation():
    """Verify that compute_section_budget correctly allocates targets summing to ~1250 within [1100, 1400]."""
    targets = []
    maxima = []
    for i in range(1, 6):
        target, max_words = compute_section_budget(
            section_index=i,
            total_sections=5,
            target_total_words=TARGET_ESSAY_WORDS,
        )
        targets.append(target)
        maxima.append(max_words)

    # Section 1 (Intro) and Section 5 (Conclusion) have focused budgets; Sections 2-4 have deeper budgets
    assert targets[0] == 230  # Intro target
    assert maxima[0] == 260
    assert targets[1] == 260  # Section 2 target
    assert maxima[1] == 285
    assert targets[2] == 260  # Section 3 target
    assert maxima[2] == 285
    assert targets[3] == 260  # Section 4 target
    assert maxima[3] == 285
    assert targets[4] == 240  # Conclusion target
    assert maxima[4] == 270

    # Total targets equal exactly 1,250 words
    assert sum(targets) == TARGET_ESSAY_WORDS
    # Sum of maximum caps strictly bounded within the accepted range (< 1,400)
    assert sum(maxima) <= MAX_ACCEPTABLE_WORDS


def test_split_sentences_safely_preserves_citations_and_links():
    """Verify that split_sentences_safely never cuts inside citations, markdown links, or decimals."""
    sample = (
        "Founders must talk directly to prospects [1]. "
        "According to [Jason's Guide](https://example.com/saas), early discovery is non-negotiable. "
        "They scaled ARR by 2.5% per week. "
        "Do not delegate sales too early."
    )
    sentences = split_sentences_safely(sample)
    assert len(sentences) == 4
    assert sentences[0] == "Founders must talk directly to prospects [1]."
    assert "[Jason's Guide](https://example.com/saas)" in sentences[1]
    assert "2.5%" in sentences[2]
    assert sentences[3] == "Do not delegate sales too early."


def test_trim_section_to_budget_preserves_structure_and_citations():
    """Verify that trim_section_to_budget reduces an overlong ~550-word section without breaking structure."""
    overlong_section = (
        "## The 10-Customer Rule\n\n"
        "Founders often believe that hiring a salesperson will solve their revenue problems immediately. "
        "However, early-stage selling is not sales execution; it is product discovery [1]. "
        "When you outsource sales prematurely, you sever the feedback loop between the market and product development. "
        "Every single discovery call with a prospect reveals pricing friction, positioning gaps, and product bugs. "
        "A hired account executive cannot rewrite code or alter product strategy mid-call. "
        "Only the founders possess the organizational authority to pivot the core messaging in real time.\n\n"
        "Here are three non-negotiable rules every SaaS founder must enforce:\n"
        "- Personally demo the software to at least thirty qualified prospects.\n"
        "- Close ten paying accounts without sales assistance.\n"
        "- Maintain a living document of common buyer objections and onboarding hurdles.\n\n"
        "Rambling paragraph one: Founders frequently convince themselves that their time is too valuable for cold outreach. "
        "They assume that senior sales professionals know how to sell better than they do. "
        "In enterprise software, this assumption consistently proves catastrophic. "
        "Sales reps excel at repeating a proven formula, but in early-stage startups there is no formula to execute yet. "
        "You are asking a rep to build the product-market fit playbook from complete scratch.\n\n"
        "Rambling paragraph two: Furthermore, the economic cost of premature sales hiring extends far beyond base salary. "
        "When reps fail to hit their targets, founders waste months diagnosing whether the problem is rep performance. "
        "Usually, the real problem is product-market fit and messaging clarity. "
        "By the time the founder realizes this reality, nine to twelve months of runway have evaporated. "
        "This is the most common reason seed-stage companies fail to reach Series A milestones.\n\n"
        "Rambling paragraph three: In conclusion, keeping sales founder-led is not a temporary inconvenience. "
        "It is the single most valuable strategic advantage an early-stage company possesses. "
        "Stay close to the customer, learn what makes them buy, and only recruit reps once the path is clear."
    )
    initial_words = count_words(overlong_section)
    assert initial_words > 300

    trimmed = trim_section_to_budget(
        section_markdown=overlong_section,
        target_words=260,
        max_words=285,
    )
    trimmed_words = count_words(trimmed)
    assert trimmed_words <= 285
    assert trimmed_words >= 150

    # Structural elements must be preserved
    assert trimmed.startswith("## The 10-Customer Rule")
    assert "[1]" in trimmed  # Grounded citation preserved
    assert "- Personally demo the software" in trimmed  # Bullet list preserved
    assert trimmed.count("**") % 2 == 0  # Balanced formatting


def test_trim_section_preserves_intro_hook_and_conclusion_takeaway():
    """Verify that Section 1 retains the opening hook/thesis and Section 5 retains the closing takeaway."""
    # Intro section
    intro_markdown = (
        "# Why Founders Must Not Outsource Sales\n\n"
        "Most founders hire sales reps too early and burn half their seed round. "
        "They think outsourcing sales accelerates revenue. It does the exact opposite [1].\n\n"
        "Rambling elaboration paragraph about sales reps and industry trends that expands word count needlessly. "
        "This paragraph goes on and on analyzing enterprise trends and macroeconomic conditions that are not essential.\n\n"
        "Another long repetitive paragraph repeating the same concepts across several lines."
    )
    trimmed_intro = trim_section_to_budget(
        section_markdown=intro_markdown,
        target_words=230,
        max_words=260,
        is_intro=True,
    )
    # Hook / thesis preserved at top
    assert "Most founders hire sales reps too early" in trimmed_intro
    assert "[1]" in trimmed_intro

    # Conclusion section
    conclusion_markdown = (
        "## 30-Day Founder Action Plan\n\n"
        "Execution discipline separates breakout SaaS companies from those that stall out in seed stage.\n\n"
        "- Audit your direct customer interactions.\n"
        "- Personally close your next five enterprise prospects.\n"
        "- Document all conversion objections.\n\n"
        "Rambling middle paragraph that adds excessive prose to the conclusion without delivering new insight. "
        "Founders must remember that sales is discovery and discovery is sales over and over again.\n\n"
        "The Bottom Line: Never hire a salesperson until you have personally closed your first 10 customers."
    )
    trimmed_conclusion = trim_section_to_budget(
        section_markdown=conclusion_markdown,
        target_words=240,
        max_words=270,
        is_conclusion=True,
    )
    # Final takeaway preserved at end
    assert "The Bottom Line: Never hire a salesperson" in trimmed_conclusion
    assert "- Audit your direct customer interactions" in trimmed_conclusion


@pytest.mark.asyncio
async def test_overlong_draft_similar_to_live_2813_words_trimmed_to_compliant_range(db_session: Session):
    """Verify that an overlong draft similar to the live 2813-word test is cleanly trimmed into 1100-1400 words."""
    session = create_session(db=db_session, title="Overlong Draft Test")
    mock_retrieval_svc = MagicMock(spec=SemanticRetrievalService)
    citation = _mock_citation()
    mock_retrieval_svc.retrieve.return_value = RetrievalResponse(
        query="AI sales agents Jason Lemkin",
        status="success",
        items=[citation],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    # Outline
    mock_outline_text = (
        "**TITLE:** AI Sales Agents: What Founders Must Know Before Automating\n"
        "**AUDIENCE:** Early-stage SaaS founders\n"
        "**HOOK:** AI sales agents promise automated revenue, but automating a broken process only accelerates failure.\n"
        "**THESIS:** Founders must personally master discovery and close 10 customers before deploying AI agents.\n"
        "**SECTION 1:** The Automation Illusion | PURPOSE: Hook and core thesis | EVIDENCE: [1]\n"
        "**SECTION 2:** The 10-Customer Discovery Baseline | PURPOSE: Threshold before automation | EVIDENCE: [1]\n"
        "**SECTION 3:** Where AI Agents Actually Work | PURPOSE: Practical operational playbook | EVIDENCE: [1]\n"
        "**SECTION 4:** Dangerous Traps and Data Pollution | PURPOSE: Pitfalls of premature agents | EVIDENCE: [1]\n"
        "**SECTION 5:** The 30-Day Implementation Checklist | PURPOSE: Concrete action steps | EVIDENCE: [1]\n"
        "**TAKEAWAY:** Automate only what is already proven.\n"
    )

    # Overlong section draft (~550 words per section, exactly like the observed 2,813-word output)
    overlong_section_text = (
        "Founders often believe that deploying AI sales agents will immediately solve their pipeline generation problems. "
        "However, early-stage selling is fundamentally an exercise in customer discovery, not mechanical execution [1]. "
        "When you deploy AI agents prematurely, you sever the vital feedback loop between the market and product engineering. "
        "Every single customer discovery call reveals subtle pricing objections, unexpected feature requests, and messaging friction. "
        "An AI sales agent or autonomous SDR cannot interpret ambiguous customer body language or modify the value proposition on the fly. "
        "Only a founder has the contextual authority and strategic vision to pivot the company positioning in real time.\n\n"
        "Jason Lemkin emphasizes that closing your first ten paying customers yourself is completely non-negotiable [1]. "
        "Until ten customers have signed actual contracts and wired payments, you do not have a validated sales playbook to automate. "
        "Automating outbound before this milestone guarantees that you burn your domain reputation on an unproven value proposition. "
        "To build enduring sales velocity, founders must embrace the following execution rules:\n"
        "- Personally conduct every customer demo until ten paying accounts are secured.\n"
        "- Document the exact sequence of buyer questions and purchase triggers.\n"
        "- Map out the customer onboarding journey to understand why renewals happen.\n\n"
        "Elaborative background prose: Many early-stage software founders find sales uncomfortable and seek to automate it away. "
        "They see new AI agent platforms and think they can bypass the painful work of customer objection handling. "
        "This is an expensive misunderstanding of what AI tools do well. "
        "AI agents are powerful force multipliers for existing, validated playbooks with high conversion rates. "
        "They are not product strategists capable of diagnosing why an early prototype is failing to convert.\n\n"
        "Secondary analysis paragraph: Consider the compounding damage of sending thousands of uncalibrated AI sales emails. "
        "Prospective buyers develop brand fatigue before your product even matures to competitive readiness. "
        "Furthermore, the feedback you receive from low-intent automated replies is noisy and misleading. "
        "You risk prioritizing features for tire-kickers rather than high-value ideal customer profiles. "
        "Stay founder-led in your sales motions until repeatable patterns emerge across multiple quarters.\n\n"
        "The Bottom Line: Do not deploy AI sales agents until you have personally closed 10 customers and validated the playbook."
    )

    mock_pi = MagicMock(spec=PiClient)
    # Stage 1 + 5 sections of ~550 words each (totaling ~2,750+ words without trimming)
    mock_pi.generate_response = AsyncMock(
        side_effect=[
            PiGenerationResult(text=mock_outline_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=overlong_section_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=overlong_section_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=overlong_section_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=overlong_section_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=overlong_section_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        ]
    )

    orchestrator = Ship30EssayOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval_svc,
    )

    result = await orchestrator.generate_essay(
        session_id=session.id,
        topic="What can early-stage SaaS founders learn about AI sales agents from Jason Lemkin?",
        audience="Early-stage SaaS founders",
        db=db_session,
    )

    # Word count must land cleanly within the 1100-1400 accepted range
    assert MIN_ACCEPTABLE_WORDS <= result.word_count <= MAX_ACCEPTABLE_WORDS
    assert result.status == "completed"

    # Title extracted cleanly from markdown bold outline without robotic prefix
    assert "AI Sales Agents:" in result.title
    assert "The Operator's Playbook:" not in result.title

    # Markdown structure and citations preserved
    assert result.content.startswith(f"# {result.title}")
    assert "### Sources" in result.content
    assert "[1]" in result.content
    assert len(result.citations) >= 1


@pytest.mark.asyncio
async def test_model_ignoring_budget_short_draft_returns_honest_partial_status(db_session: Session):
    """Verify that when a model outputs an underlength draft, orchestrator does NOT manufacture filler and reports 'partial'."""
    session = create_session(db=db_session, title="Short Draft Test")
    mock_retrieval_svc = MagicMock(spec=SemanticRetrievalService)
    citation = _mock_citation()
    mock_retrieval_svc.retrieve.return_value = RetrievalResponse(
        query="sales timing",
        status="success",
        items=[citation],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    mock_outline_text = (
        "TITLE: Founder Sales Playbook\n"
        "AUDIENCE: SaaS Founders\n"
        "HOOK: Short hook.\n"
        "THESIS: Short thesis.\n"
        "SECTION 1: Part 1 | PURPOSE: P1 | EVIDENCE: [1]\n"
        "SECTION 2: Part 2 | PURPOSE: P2 | EVIDENCE: [1]\n"
        "SECTION 3: Part 3 | PURPOSE: P3 | EVIDENCE: [1]\n"
        "SECTION 4: Part 4 | PURPOSE: P4 | EVIDENCE: [1]\n"
        "SECTION 5: Part 5 | PURPOSE: P5 | EVIDENCE: [1]\n"
        "TAKEAWAY: Done.\n"
    )

    # Very short section (~40 words each -> total ~200 words, far below 1100)
    short_section_text = (
        "## Section Heading\n\n"
        "Founders must close the first ten customers personally before hiring any sales representatives [1]. "
        "This ensures that product feedback flows directly into engineering without dilution."
    )

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(
        side_effect=[
            PiGenerationResult(text=mock_outline_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=short_section_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=short_section_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=short_section_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=short_section_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=short_section_text, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        ]
    )

    orchestrator = Ship30EssayOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval_svc,
    )

    result = await orchestrator.generate_essay(
        session_id=session.id,
        topic="Sales hiring timing",
        db=db_session,
    )

    # Must honestly report 'partial' because total words < 1100
    assert result.status == "partial"
    assert result.word_count < MIN_ACCEPTABLE_WORDS
    assert result.word_count > 0


def test_outline_parsing_handles_markdown_bold_and_prefixes():
    """Verify that _parse_outline_response handles markdown bold tags and generates natural fallback titles."""
    orchestrator = Ship30EssayOrchestrator(pi_client=MagicMock(spec=PiClient))

    markdown_outline = (
        "**TITLE:** AI Sales Agents: The Founder's Guide\n"
        "**AUDIENCE:** SaaS Founders\n"
        "**THESIS:** Automate only what is already proven.\n"
        "**SECTION 1:** Opening Hook | PURPOSE: Core problem | EVIDENCE: [1]\n"
        "**SECTION 2:** Core Threshold | PURPOSE: 10 customers | EVIDENCE: [1]\n"
        "**SECTION 3:** Playbook | PURPOSE: Tactics | EVIDENCE: [1]\n"
        "**SECTION 4:** Traps | PURPOSE: Pitfalls | EVIDENCE: [1]\n"
        "**SECTION 5:** Action Plan | PURPOSE: 30 days | EVIDENCE: [1]\n"
    )

    title, thesis, sections = orchestrator._parse_outline_response(
        outline_text=markdown_outline,
        topic="What can early-stage SaaS founders learn about AI sales agents from Jason Lemkin?",
        audience="SaaS Founders",
    )
    assert title == "AI Sales Agents: The Founder's Guide"
    assert thesis == "Automate only what is already proven."
    assert len(sections) == 5

    # Test natural fallback headline when title is omitted from outline
    empty_outline = "No outline structure provided here."
    fallback_title, _, _ = orchestrator._parse_outline_response(
        outline_text=empty_outline,
        topic="What can early-stage SaaS founders learn about AI sales agents from Jason Lemkin?",
        audience="Early-stage SaaS founders",
    )
    assert "The Operator's Playbook:" not in fallback_title
    assert "Ai Sales Agents:" in fallback_title or "Jason Lemkin" in fallback_title


# ---------------------------------------------------------------------------
# Phase 5A Correction 6: Code Fence Normalization & Editorial Voice Quality
# ---------------------------------------------------------------------------

def test_clean_section_markdown_strips_outer_code_fences_and_preserves_inner():
    """Verify that clean_section_markdown removes outer ```markdown code fences while preserving content."""
    raw_section = (
        "```markdown\n"
        "## The 10-Customer Rule\n\n"
        "Founders must talk directly to prospects before hiring sales reps [1].\n\n"
        "- Personally demo the software to qualified leads.\n"
        "- Validate pricing sensitivity.\n\n"
        "Execution discipline is **essential** for SaaS growth.\n"
        "Check out [Jason's Playbook](https://example.com/saas) for details.\n"
        "```"
    )
    cleaned = clean_section_markdown(raw_section)
    assert not cleaned.startswith("```")
    assert not cleaned.endswith("```")
    assert "```markdown" not in cleaned
    assert cleaned.startswith("## The 10-Customer Rule")
    assert "[1]" in cleaned  # Citation preserved
    assert "[Jason's Playbook](https://example.com/saas)" in cleaned  # Markdown link preserved
    assert "**essential**" in cleaned  # Bold preserved
    assert "- Personally demo the software" in cleaned  # Bullets preserved


def test_clean_section_markdown_normalizes_episode_titles_and_duplicate_h1():
    """Verify that duplicated episode titles and redundant H1 headers are cleaned or demoted."""
    # 1. Section with duplicate episode title as H1
    raw_with_ep_title = (
        "# When to Hire Sales - Guest: Jason Lemkin\n\n"
        "## The 10-Customer Rule\n\n"
        "Founders must close the first ten customers personally [1]."
    )
    cleaned_ep = clean_section_markdown(
        text=raw_with_ep_title,
        known_episode_titles=["When to Hire Sales"],
    )
    assert "# When to Hire Sales" not in cleaned_ep
    assert "Guest: Jason Lemkin" not in cleaned_ep
    assert cleaned_ep.startswith("## The 10-Customer Rule")

    # 2. Section with duplicate essay title as H1
    essay_title = "AI Sales Agents: The Founder's Guide"
    raw_with_dup_title = (
        f"# {essay_title}\n\n"
        "## Opening Hook\n\n"
        "Early discovery cannot be outsourced."
    )
    cleaned_dup = clean_section_markdown(
        text=raw_with_dup_title,
        essay_title=essay_title,
    )
    assert f"# {essay_title}" not in cleaned_dup
    assert cleaned_dup.startswith("## Opening Hook")

    # 3. Accidental section H1 demoted to H2
    raw_with_h1 = (
        "# The Tactical Playbook\n\n"
        "Follow these execution mechanics."
    )
    cleaned_h1 = clean_section_markdown(text=raw_with_h1)
    assert cleaned_h1.startswith("## The Tactical Playbook")


def test_normalize_editorial_voice_converts_first_person_statements():
    """Verify that normalize_editorial_voice converts first-person statements into objective editorial prose while protecting authentic quotations."""
    sample = (
        "As the founder of a SaaS company, I often wonder when to hire salespeople. "
        "In my experience, premature delegation destroys early discovery. "
        "I have found that closing 10 accounts personally builds the right foundation."
    )
    normalized = normalize_editorial_voice(sample)
    assert "As the founder of a SaaS company, I often wonder" not in normalized
    assert "Early-stage SaaS founders often wonder" in normalized
    assert "In my experience," not in normalized
    assert "In practice," in normalized
    assert "I have found that" not in normalized
    assert "Grounded evidence demonstrates that" in normalized

    # Authentic guest quotations must remain intact even if they contain first-person language
    quote_sample = 'Jason Lemkin stated: "In my experience, founders must close 10 customers themselves." This is essential.'
    quote_normalized = normalize_editorial_voice(quote_sample)
    assert '"In my experience, founders must close 10 customers themselves."' in quote_normalized


@pytest.mark.asyncio
async def test_final_essay_assembly_guarantees_exactly_one_h1_and_no_fences(db_session: Session):
    """Verify that the assembled final essay has exactly one H1, zero code fences, and valid status."""
    session = create_session(db=db_session, title="Clean Assembly Test")
    mock_retrieval_svc = MagicMock(spec=SemanticRetrievalService)
    citation = _mock_citation(title="When to Hire Sales", guest="Jason Lemkin")
    mock_retrieval_svc.retrieve.return_value = RetrievalResponse(
        query="sales hiring",
        status="success",
        items=[citation],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    mock_outline = (
        "TITLE: AI Sales Agents: The Operational Blueprint\n"
        "AUDIENCE: SaaS Founders\n"
        "HOOK: Most founders delegate discovery too early.\n"
        "THESIS: Close 10 customers yourself first.\n"
        "SECTION 1: The Automation Dilemma | PURPOSE: Hook and thesis | EVIDENCE: [1]\n"
        "SECTION 2: The 10-Customer Threshold | PURPOSE: Core metric | EVIDENCE: [1]\n"
        "SECTION 3: The Operational Playbook | PURPOSE: Tactical steps | EVIDENCE: [1]\n"
        "SECTION 4: Dangerous Shortcuts | PURPOSE: Common pitfalls | EVIDENCE: [1]\n"
        "SECTION 5: 30-Day Decision Framework | PURPOSE: Final takeaway | EVIDENCE: [1]\n"
        "TAKEAWAY: Master discovery before automating.\n"
    )

    # Section drafts wrapped in ```markdown code fences with duplicate episode titles and accidental H1s
    section_with_fence_and_ep_title = (
        "```markdown\n"
        "# When to Hire Sales - Guest: Jason Lemkin\n\n"
        "## The Automation Dilemma\n\n"
        "Founders often believe that deploying AI sales agents will immediately solve their pipeline generation problems. "
        "However, early-stage selling is fundamentally an exercise in customer discovery, not mechanical execution [1]. "
        "When you deploy AI agents prematurely, you sever the vital feedback loop between the market and product engineering. "
        "Every single customer discovery call reveals subtle pricing objections, unexpected feature requests, and messaging friction. "
        "An AI sales agent cannot interpret ambiguous customer body language or modify the value proposition on the fly. "
        "Only a founder has the contextual authority and strategic vision to pivot the company positioning in real time.\n\n"
        "Jason Lemkin emphasizes that closing your first ten paying customers yourself is completely non-negotiable [1]. "
        "Until ten customers have signed actual contracts and wired payments, you do not have a validated sales playbook to automate. "
        "To build enduring sales velocity, founders must embrace the following execution rules:\n"
        "- Personally conduct every customer demo until ten paying accounts are secured.\n"
        "- Document the exact sequence of buyer questions and purchase triggers.\n"
        "- Map out the customer onboarding journey to understand why renewals happen.\n\n"
        "Documenting discovery feedback allows the founding team to refine the ideal customer profile rapidly. "
        "When founders handle the earliest sales pipeline personally, closing velocity accelerates and unit economics stabilize.\n\n"
        "The Bottom Line: Master discovery before automating.\n"
        "```"
    )

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(
        side_effect=[
            PiGenerationResult(text=mock_outline, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=section_with_fence_and_ep_title, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=section_with_fence_and_ep_title, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=section_with_fence_and_ep_title, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=section_with_fence_and_ep_title, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=section_with_fence_and_ep_title, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        ]
    )

    orchestrator = Ship30EssayOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval_svc,
    )

    result = await orchestrator.generate_essay(
        session_id=session.id,
        topic="What can early-stage SaaS founders learn about AI sales agents from Jason Lemkin?",
        audience="SaaS Founders",
        db=db_session,
    )

    # 1. Zero ```markdown code fences
    assert "```markdown" not in result.content
    assert not result.content.strip().startswith("```")

    # 2. Exactly one H1 in the entire essay
    h1_headings = re.findall(r"^#\s+[^#]", result.content, flags=re.MULTILINE)
    assert len(h1_headings) == 1
    assert result.content.startswith("# AI Sales Agents: The Operational Blueprint")

    # 3. No episode title inserted as an H1 heading
    assert "# When to Hire Sales" not in result.content

    # 4. Word count accurately counted on body and within accepted range
    assert MIN_ACCEPTABLE_WORDS <= result.word_count <= MAX_ACCEPTABLE_WORDS
    assert result.status == "completed"

    # 5. Citations and Sources block preserved
    assert "[1]" in result.content
    assert "### Sources" in result.content
    assert len(result.citations) >= 1


@pytest.mark.asyncio
async def test_malformed_output_with_insufficient_sections_returns_partial_status(db_session: Session):
    """Verify that malformed or incomplete output with fewer than 3 sections honestly returns 'partial'."""
    session = create_session(db=db_session, title="Incomplete Test")
    mock_retrieval_svc = MagicMock(spec=SemanticRetrievalService)
    citation = _mock_citation()
    mock_retrieval_svc.retrieve.return_value = RetrievalResponse(
        query="sales timing",
        status="success",
        items=[citation],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    # Outline with only 1 section
    mock_outline = (
        "TITLE: Minimal Essay\n"
        "AUDIENCE: Founders\n"
        "HOOK: Hook.\n"
        "THESIS: Thesis.\n"
        "SECTION 1: Part 1 | PURPOSE: P1 | EVIDENCE: [1]\n"
        "TAKEAWAY: Done.\n"
    )

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(
        side_effect=[
            PiGenerationResult(text=mock_outline, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            # Only section 1 returns text, but others time out or return empty
            PiGenerationResult(text="## Part 1\nShort text.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text="## Part 2\nShort text.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text="## Part 3\nShort text.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text="## Part 4\nShort text.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text="## Part 5\nShort text.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        ]
    )

    orchestrator = Ship30EssayOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval_svc,
    )

    result = await orchestrator.generate_essay(
        session_id=session.id,
        topic="sales timing",
        db=db_session,
    )

    # Word count is far below 1100, must honestly report 'partial'
    assert result.status == "partial"
    assert result.word_count < MIN_ACCEPTABLE_WORDS


# ---------------------------------------------------------------------------
# Phase 5A Correction 8: Content Integrity & Citation Reconciliation Tests
# ---------------------------------------------------------------------------

def test_duplicate_h1_h2_article_title_removal():
    """1. Verify removal or replacement of duplicate H2 headings matching the article title."""
    title = "Ai Sales Agents: Jason Lemkin's Lessons for Early-stage SaaS founders"
    raw_markdown = (
        f"# {title}\n\n"
        f"## {title}\n\n"
        "Founders often believe that deploying AI sales agents will immediately solve early pipeline problems.\n\n"
        "## Tactical Execution Mechanics\n\n"
        "Follow these execution mechanics before automating."
    )
    # clean_section_markdown handles duplicate title removal/replacement
    cleaned = clean_section_markdown(
        text=raw_markdown,
        is_intro=True,
        essay_title=title,
    )
    # The duplicate H2 is replaced with the clean structural section heading
    assert f"## {title}" not in cleaned
    assert "## The Core Tension & Strategic Dilemma" in cleaned
    assert "## Tactical Execution Mechanics" in cleaned
    assert is_duplicate_title(title, title) is True
    assert is_duplicate_title("Tactical Execution Mechanics", title) is False


def test_standalone_retrieval_metadata_removal():
    """2. Verify standalone retrieval prompt metadata and inline trailers are stripped."""
    raw_section = (
        "## The Automation Dilemma\n\n"
        "[1] (Episode: We replaced our sales team with 20 AI agents—here’s what happened next | Jason Lemkin (SaaStr), Guest: Jason M Lemkin)\n\n"
        "Early customer discovery must be managed directly by founders [1] (Episode: We replaced our sales team with 20 AI agents | Guest: Jason Lemkin).\n\n"
        "- Evidence: [5] (Podcast - 30 Days of Growth in SaaS: How to Handle a Sales Team Replacement | Guest: Jason Lemkin)\n\n"
        "- Master discovery calls personally before writing scripts [1].\n"
        "- Evidence: [1]\n"
        "- Keep continuous customer feedback loops intact [1]."
    )
    cleaned, stripped_indices = strip_metadata_leaks(raw_section)
    assert "[1] (Episode: We replaced our sales team" not in cleaned
    assert "- Evidence: [5]" not in cleaned
    assert "- Evidence: [1]" not in cleaned
    assert "Guest: Jason" not in cleaned
    # Legitimate inline citation and bullets remain
    assert "managed directly by founders [1]." in cleaned
    assert "- Master discovery calls personally before writing scripts [1]." in cleaned
    assert "- Keep continuous customer feedback loops intact [1]." in cleaned
    assert 5 in stripped_indices or 1 in stripped_indices


def test_malformed_and_multiline_metadata_leak_removal():
    """Verify handling of malformed metadata fragments like [1], Guest: ...), multiline headers, and authentic guest mentions."""
    malformed_text = (
        "Founders learn through discovery [1], Guest: Jason M Lemkin).\n\n"
        "Jason Lemkin emphasized that direct founder discovery creates the foundation for future sales automation [1].\n\n"
        'Guest Jason Lemkin stated: "You cannot outsource early customer discovery." [1]\n\n'
        "[1], Guest: Jason M Lemkin)\n"
        "- Evidence: [2] (Episode: How to Hire Sales (Part 1), Guest: Jason Lemkin)\n"
        "Retention metrics matter [1]."
    )
    cleaned, stripped_indices = strip_metadata_leaks(malformed_text)
    # The malformed fragment in prose is cleaned to legitimate citation [1]
    assert "Founders learn through discovery [1]." in cleaned
    assert "Guest: Jason M Lemkin)" not in cleaned
    # Authentic narrative mentions and genuine quotes are preserved
    assert "Jason Lemkin emphasized that direct founder discovery" in cleaned
    assert 'Guest Jason Lemkin stated: "You cannot outsource early customer discovery." [1]' in cleaned
    assert "Retention metrics matter [1]." in cleaned
    assert 2 in stripped_indices or 1 in stripped_indices


def test_detection_of_inline_unverified_citation_marker():
    """3. Verify detection and removal of inline [5] when verified sources contain only [1] and [4]."""
    evidence = [
        EvidenceEntry(
            index=1,
            source=_mock_citation(title="AI Sales Agents", guest="Jason Lemkin"),
            header="[1] Episode: AI Sales Agents",
            excerpt="Master discovery first.",
        ),
        EvidenceEntry(
            index=4,
            source=_mock_citation(title="SaaS Scaling Rules", guest="Jason Lemkin"),
            header="[4] Episode: SaaS Scaling Rules",
            excerpt="Scale after validation.",
        ),
    ]
    sample_text = (
        "Early discovery cannot be delegated [1]. "
        "Sales automation without repeatable positioning fails rapidly [5]. "
        "Validate pricing and objection patterns directly [4]."
    )
    sanitized, valid_cited, invalid_cited = reconcile_and_sanitize_essay_citations(
        text=sample_text,
        evidence_entries=evidence,
    )
    assert invalid_cited == [5]
    assert valid_cited == [1, 4]
    # Unsupported [5] stripped cleanly without damaging the sentence
    assert "[5]" not in sanitized
    assert "Sales automation without repeatable positioning fails rapidly." in sanitized
    assert "[1]" in sanitized
    assert "[4]" in sanitized


def test_no_fabricated_source_entry_created_for_invalid_marker():
    """4. Verify that no fabricated source entry is created for an invalid/unsupported marker."""
    evidence = [
        EvidenceEntry(
            index=1,
            source=_mock_citation(title="AI Sales Agents", guest="Jason Lemkin"),
            header="[1] Episode: AI Sales Agents",
            excerpt="Master discovery first.",
        ),
        EvidenceEntry(
            index=4,
            source=_mock_citation(title="SaaS Scaling Rules", guest="Jason Lemkin"),
            header="[4] Episode: SaaS Scaling Rules",
            excerpt="Scale after validation.",
        ),
    ]
    valid_cited = [1, 4]
    sources_section = format_essay_sources(evidence_entries=evidence, cited_indices=valid_cited)
    assert "[1]" in sources_section
    assert "[4]" in sources_section
    assert "[5]" not in sources_section
    assert "30 Days of Growth" not in sources_section
    # Even if [5] was passed to format_essay_sources, it is omitted because it's not in evidence
    sources_with_invalid = format_essay_sources(evidence_entries=evidence, cited_indices=[1, 4, 5])
    assert "[5]" not in sources_with_invalid


def test_placeholder_and_unfinished_author_note_detection():
    """5. Verify detection and removal of placeholder author notes and drafting scaffolding."""
    raw_text = (
        "## Tactical Playbook\n\n"
        "Founders must validate unit economics early.\n\n"
        "Please replace them with concrete key insights derived from Jason Lemkin's podcast.\n\n"
        "[insert evidence here]\n\n"
        "TODO: add quantitative customer retention benchmarks.\n\n"
        "Note to author: check SaaStr episode title.\n\n"
        "The primary priority remains customer discovery."
    )
    cleaned, detected = strip_draft_artifacts(raw_text)
    assert len(detected) >= 4
    assert any("Please replace" in d for d in detected)
    assert any("insert evidence" in d for d in detected)
    assert any("TODO" in d for d in detected)
    assert any("Note to author" in d for d in detected)
    assert "Please replace" not in cleaned
    assert "[insert evidence here]" not in cleaned
    assert "TODO:" not in cleaned
    assert "Note to author:" not in cleaned
    assert "The primary priority remains customer discovery." in cleaned


@pytest.mark.asyncio
async def test_proper_partial_status_when_claim_cannot_be_safely_reconciled(db_session: Session):
    """6. Verify that an essay with an ungrounded citation [5] or author instructions returns 'partial'."""
    session = create_session(db=db_session, title="Honest Status Test")
    mock_retrieval_svc = MagicMock(spec=SemanticRetrievalService)
    citation = _mock_citation(title="AI Sales Agents", guest="Jason Lemkin")
    mock_retrieval_svc.retrieve.return_value = RetrievalResponse(
        query="ai sales agents",
        status="success",
        items=[citation],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    mock_outline = (
        "TITLE: AI Sales Agents: Jason Lemkin's Lessons for Founders\n"
        "AUDIENCE: SaaS Founders\n"
        "HOOK: Most founders automate sales prematurely.\n"
        "THESIS: Validate discovery before automating.\n"
        "SECTION 1: Core Tension | PURPOSE: Hook | EVIDENCE: [1]\n"
        "SECTION 2: Ground Rules | PURPOSE: Principles | EVIDENCE: [1]\n"
        "SECTION 3: The Playbook | PURPOSE: Tactics | EVIDENCE: [1]\n"
        "SECTION 4: Common Traps | PURPOSE: Pitfalls | EVIDENCE: [1]\n"
        "SECTION 5: Action Steps | PURPOSE: Takeaway | EVIDENCE: [1]\n"
        "TAKEAWAY: Discovery first.\n"
    )

    substantive_sec = (
        "Founders often believe that deploying AI sales agents will immediately solve early pipeline problems. "
        "However, early-stage selling is fundamentally an exercise in customer discovery, not mechanical execution [1]. "
        "When you deploy AI agents prematurely, you sever the vital feedback loop between the market and product engineering. "
        "Every single customer discovery call reveals subtle pricing objections, unexpected feature requests, and messaging friction. "
        "An AI sales agent cannot interpret ambiguous customer body language or modify the value proposition on the fly. "
        "Only a founder has the contextual authority and strategic vision to pivot the company positioning in real time.\n\n"
        "Jason Lemkin emphasizes that closing early customers yourself is completely non-negotiable [1]. "
        "Until ten customers have signed actual contracts and wired payments, you do not have a validated sales playbook to automate. "
        "To build enduring sales velocity, founders must embrace the following execution rules:\n"
        "- Personally conduct every customer demo until ten paying accounts are secured.\n"
        "- Document the exact sequence of buyer questions and purchase triggers.\n"
        "- Map out the customer onboarding journey to understand why renewals happen.\n\n"
        "Documenting discovery feedback allows the founding team to refine the ideal customer profile rapidly. "
        "When founders handle the earliest sales pipeline personally, closing velocity accelerates and unit economics stabilize. "
        "Sustainable go-to-market execution requires direct founder immersion before delegating pipeline generation to automated agents. "
        "Every customer conversation informs product roadmap decisions and establishes baseline pricing thresholds."
    )

    # Section 3 contains an unverified citation [5] referencing a nonexistent source
    sec_with_invalid_citation = (
        substantive_sec + "\n\nEvidence from unverified source suggests automated replacement [5]."
    )

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(
        side_effect=[
            PiGenerationResult(text=mock_outline, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Core Tension\n\n{substantive_sec}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Ground Rules\n\n{substantive_sec}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## The Playbook\n\n{sec_with_invalid_citation}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Common Traps\n\n{substantive_sec}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Action Steps\n\n{substantive_sec}\n\nThe Bottom Line: Master discovery before automating.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        ]
    )

    orchestrator = Ship30EssayOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval_svc,
    )

    result = await orchestrator.generate_essay(
        session_id=session.id,
        topic="AI sales agents according to Jason Lemkin",
        audience="SaaS Founders",
        db=db_session,
    )

    # Although word count is in accepted range (1100-1400), status must honestly be 'partial'
    assert MIN_ACCEPTABLE_WORDS <= result.word_count <= MAX_ACCEPTABLE_WORDS
    assert result.status == "partial"
    # [5] was cleanly stripped from final content
    assert "[5]" not in result.content
    # Sources section contains only verified [1]
    assert "[1]" in result.content
    assert "### Sources" in result.content


def test_preservation_of_legitimate_quotations_valid_citations_and_markdown():
    """7. Verify preservation of authentic quotes, valid citations, bolding, lists, and numerical metrics."""
    raw_text = (
        "## Tactical Playbook\n\n"
        'Jason Lemkin noted: "You cannot outsource early customer discovery." [1]\n\n'
        "In 2024, our analysis demonstrates that closing **10 enterprise customers** manually yields $1.5M ARR [1].\n\n"
        "Here are 3 concrete execution steps:\n"
        "1. Conduct initial discovery calls personally.\n"
        "2. Document common friction points.\n"
        "3. Review unit economics weekly.\n\n"
        "- Core principle: **Do not delegate discovery prematurely** [1].\n"
        "- Learn more at [SaaStr](https://www.saastr.com).\n"
    )
    cleaned = clean_section_markdown(
        text=raw_text,
        essay_title="AI Sales Agents",
    )
    # Quotes preserved
    assert '"You cannot outsource early customer discovery."' in cleaned
    # Valid citations preserved
    assert "[1]" in cleaned
    # Bold text preserved
    assert "**10 enterprise customers**" in cleaned
    assert "**Do not delegate discovery prematurely**" in cleaned
    # Numbered list and metrics preserved
    assert "1. Conduct initial discovery calls personally." in cleaned
    assert "$1.5M ARR" in cleaned
    # Markdown links preserved
    assert "[SaaStr](https://www.saastr.com)" in cleaned


def test_accurate_word_counting_after_cleanup():
    """8. Verify that word counting accurately measures body text after artifact removal and excludes Sources."""
    body_markdown = (
        "# AI Sales Agents: The Founder's Dilemma\n\n"
        "## The Core Tension & Strategic Dilemma\n\n"
        "Founders often believe that deploying AI sales agents will immediately solve early pipeline problems. "
        "Please replace them with concrete key insights derived from Jason Lemkin's podcast.\n\n"
        "- Evidence: [5] (Podcast - 30 Days of Growth in SaaS: How to Handle a Sales Team Replacement | Guest: Jason Lemkin)\n\n"
        "Early discovery must be managed directly by founders [1]."
    )
    evidence = [
        EvidenceEntry(
            index=1,
            source=_mock_citation(title="AI Sales Agents", guest="Jason Lemkin"),
            header="[1] Episode: AI Sales Agents",
            excerpt="Early discovery must be managed directly.",
        )
    ]
    # Clean draft artifacts and reconcile citations
    sanitized, _ = strip_draft_artifacts(body_markdown)
    sanitized, valid_cited, _ = reconcile_and_sanitize_essay_citations(sanitized, evidence)
    words_after_cleanup = count_words(sanitized)

    # Sources section added
    sources = format_essay_sources(evidence, valid_cited)
    full_text = sanitized + sources

    # True body word count excludes Sources footnote metadata
    assert words_after_cleanup == count_words(sanitized)
    assert count_words(full_text) > words_after_cleanup
    assert "Please replace" not in sanitized
    assert "- Evidence: [5]" not in sanitized


def test_preservation_of_final_practical_takeaway():
    """9. Verify that trim_section_to_budget preserves the final practical takeaway in Section 5."""
    long_conclusion = (
        "## The 30-Day Decision Framework\n\n"
        "Executing an AI sales automation strategy requires disciplined founder leadership and rigorous checkpoints. "
        "When teams skip customer discovery, they end up training automated agents on broken messaging and ambiguous value propositions. "
        "Founders must spend the initial thirty days listening directly to customer objections and refining positioning. "
        "Only after repeatable conversion patterns emerge should repetitive pipeline tasks be handed off to software agents.\n\n"
        "The following execution checklist governs the rollout:\n"
        "- Conduct at least 25 discovery calls personally before writing agent scripts.\n"
        "- Map out buyer questions to identify where deals typically stall.\n"
        "- Establish non-negotiable conversion milestones for each qualification stage.\n\n"
        "Execution rigor separates breakout SaaS products from companies that burn capital on premature automation.\n\n"
        "**The Bottom Line: Master customer discovery yourself before deploying AI sales agents.**"
    )
    trimmed = trim_section_to_budget(
        section_markdown=long_conclusion,
        target_words=120,
        max_words=140,
        is_conclusion=True,
    )
    # The final takeaway must survive trimming
    assert "**The Bottom Line: Master customer discovery yourself before deploying AI sales agents.**" in trimmed
    assert count_words(trimmed) <= 140


def test_existing_essay_api_and_postgresql_persistence_compatibility(client: TestClient, db_session: Session):
    """10. Verify existing essay API response and PostgreSQL persistence compatibility."""
    session = create_session(db=db_session, title="Persistence Check")
    citation = _mock_citation(title="AI Sales Agents", guest="Jason Lemkin")

    with patch("backend.app.retrieval.service.SemanticRetrievalService.retrieve") as mock_retrieve, \
         patch("backend.app.agent.pi_client.PiClient.generate_response") as mock_pi:

        mock_retrieve.return_value = RetrievalResponse(
            query="sales agents",
            status="success",
            items=[citation],
            coverage=_mock_coverage(),
            disclaimer=None,
        )

        mock_outline = (
            "TITLE: AI Sales Agents: Jason Lemkin's Lessons for Founders\n"
            "AUDIENCE: SaaS Founders\n"
            "HOOK: Automating sales prematurely burns capital.\n"
            "THESIS: Close early accounts yourself.\n"
            "SECTION 1: Core Tension | PURPOSE: Hook | EVIDENCE: [1]\n"
            "SECTION 2: Ground Rules | PURPOSE: Principles | EVIDENCE: [1]\n"
            "SECTION 3: The Playbook | PURPOSE: Tactics | EVIDENCE: [1]\n"
            "SECTION 4: Common Traps | PURPOSE: Pitfalls | EVIDENCE: [1]\n"
            "SECTION 5: Action Steps | PURPOSE: Takeaway | EVIDENCE: [1]\n"
            "TAKEAWAY: Master discovery first.\n"
        )

        sec_body = (
            "Founders often believe that deploying AI sales agents will immediately solve early pipeline problems. "
            "However, early-stage selling is fundamentally an exercise in customer discovery, not mechanical execution [1]. "
            "When you deploy AI agents prematurely, you sever the vital feedback loop between the market and product engineering. "
            "Every single customer discovery call reveals subtle pricing objections, unexpected feature requests, and messaging friction. "
            "An AI sales agent cannot interpret ambiguous customer body language or modify the value proposition on the fly. "
            "Only a founder has the contextual authority and strategic vision to pivot the company positioning in real time.\n\n"
            "Jason Lemkin emphasizes that closing early customers yourself is completely non-negotiable [1]. "
            "Until ten customers have signed actual contracts and wired payments, you do not have a validated sales playbook to automate. "
            "To build enduring sales velocity, founders must embrace the following execution rules:\n"
            "- Personally conduct every customer demo until ten paying accounts are secured.\n"
            "- Document the exact sequence of buyer questions and purchase triggers.\n"
            "- Map out the customer onboarding journey to understand why renewals happen.\n\n"
            "Documenting discovery feedback allows the founding team to refine the ideal customer profile rapidly. "
            "When founders handle the earliest sales pipeline personally, closing velocity accelerates and unit economics stabilize. "
            "Sustainable go-to-market execution requires direct founder immersion before delegating pipeline generation to automated agents. "
            "Every customer conversation informs product roadmap decisions and establishes baseline pricing thresholds."
        )

        mock_pi.side_effect = [
            PiGenerationResult(text=mock_outline, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Core Tension\n\n{sec_body}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Ground Rules\n\n{sec_body}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## The Playbook\n\n{sec_body}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Common Traps\n\n{sec_body}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Action Steps\n\n{sec_body}\n\nThe Bottom Line: Master discovery before automating.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        ]

        response = client.post(
            f"/api/sessions/{session.id}/essay",
            json={"topic": "AI sales agents according to Jason Lemkin", "audience": "SaaS Founders"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["session_id"] == str(session.id)
        assert data["title"] == "AI Sales Agents: Jason Lemkin's Lessons for Founders"
        assert data["status"] == "completed"
        assert MIN_ACCEPTABLE_WORDS <= data["word_count"] <= MAX_ACCEPTABLE_WORDS
        assert len(data["citations"]) >= 1

        # Verify persisted essay through GET messages endpoint
        get_res = client.get(f"/api/sessions/{session.id}/messages")
        assert get_res.status_code == 200
        get_msgs = get_res.json()
        assert get_msgs["total"] == 2
        assert len(get_msgs["items"]) == 2
        assert get_msgs["items"][0]["role"] == "user"
        assert get_msgs["items"][1]["role"] == "assistant"
        assert get_msgs["items"][1]["source_metadata"]["artifact_type"] == "ship30_essay"

        # Verify PostgreSQL persistence: 2 messages created (user + assistant essay)
        msgs, total = list_messages_by_session(db=db_session, session_id=session.id)
        assert total == 2
        assert len(msgs) == 2
        user_msg = msgs[0]
        assistant_msg = msgs[1]
        assert user_msg.role == "user"
        assert assistant_msg.role == "assistant"
        assert assistant_msg.source_metadata["artifact_type"] == "ship30_essay"
        assert assistant_msg.source_metadata["word_count"] == data["word_count"]
        assert assistant_msg.source_metadata["status"] == "completed"


class TestEssayFactualGroundingSafeguards:
    """Tests for Phase 5C-B factual grounding safeguards and deterministic validation."""

    def test_unsupported_numerical_claims_detected(self):
        """Unsupported timelines and percentage allocations are flagged."""
        citation = _mock_citation(
            content="Founders should close their first 10 customers themselves before hiring sales reps."
        )
        evidence = EvidenceEntry(
            index=1,
            source=citation,
            header=f"Episode: {citation.episode_title}",
            excerpt=citation.content,
        )

        # Essay introduces unsupported timeline "100 days" and unsupported percentage "20%"
        essay_text = (
            "Founders should secure 10 customers within their first 100 days [1]. "
            "Furthermore, founders must devote 20% of their time to fundraising."
        )

        audit = verify_essay_grounding(text=essay_text, evidence_entries=[evidence], topic="Founder Sales")
        assert audit["is_grounded"] is False
        assert any("100 days" in m for m in audit["unsupported_metrics"])
        assert any("20%" in m for m in audit["unsupported_metrics"])
        assert len(audit["diagnostics"]) >= 1

    def test_supported_numerical_claims_accepted(self):
        """Supported numbers matching evidence and framework terms are accepted."""
        citation = _mock_citation(
            content="Founders should close their first 10 customers themselves before hiring sales reps."
        )
        evidence = EvidenceEntry(
            index=1,
            source=citation,
            header=f"Episode: {citation.episode_title}",
            excerpt=citation.content,
        )

        # "10 customers" matches evidence; "30-day" is framework exempt
        essay_text = (
            "Founders must personally close their first 10 customers before delegating sales [1]. "
            "Under the 30-day framework, master customer discovery before automation."
        )

        audit = verify_essay_grounding(text=essay_text, evidence_entries=[evidence], topic="Founder Sales")
        assert audit["is_grounded"] is True
        assert len(audit["unsupported_metrics"]) == 0
        assert len(audit["diagnostics"]) == 0

    def test_unsupported_direct_quotations_detected(self):
        """Direct quotations in quotes that do not match evidence are flagged."""
        citation = _mock_citation(
            content="Founders should close their first 10 customers themselves before hiring sales reps."
        )
        evidence = EvidenceEntry(
            index=1,
            source=citation,
            header=f"Episode: {citation.episode_title}",
            excerpt=citation.content,
        )

        # Fabricated quote inside quotation marks
        essay_text = (
            'Jason Lemkin warns: "You must never hire an engineer until your first sales rep hits quota" [1]. '
            "Early discovery reveals true customer objections."
        )

        audit = verify_essay_grounding(text=essay_text, evidence_entries=[evidence], topic="Founder Sales")
        assert audit["is_grounded"] is False
        assert len(audit["unsupported_quotes"]) == 1
        assert "You must never hire an engineer" in audit["unsupported_quotes"][0]

    def test_valid_verbatim_quotations_accepted(self):
        """Verbatim quotations matching transcript evidence are accepted."""
        citation = _mock_citation(
            content="Founders should close their first 10 customers themselves before hiring sales reps."
        )
        evidence = EvidenceEntry(
            index=1,
            source=citation,
            header=f"Episode: {citation.episode_title}",
            excerpt=citation.content,
        )

        # Verbatim quote from evidence
        essay_text = (
            'As Lemkin explicitly advises, "Founders should close their first 10 customers themselves before hiring sales reps" [1]. '
            "This discovery feedback is irreplaceable."
        )

        audit = verify_essay_grounding(text=essay_text, evidence_entries=[evidence], topic="Founder Sales")
        assert audit["is_grounded"] is True
        assert len(audit["unsupported_quotes"]) == 0

    def test_fabricated_company_example_detected(self):
        """Hallucinated company examples absent from evidence and topic are flagged."""
        citation = _mock_citation(
            content="Founders should close their first 10 customers themselves before hiring sales reps."
        )
        evidence = EvidenceEntry(
            index=1,
            source=citation,
            header=f"Episode: {citation.episode_title}",
            excerpt=citation.content,
        )

        # Injects Canva into an essay where Canva is not in evidence or topic
        essay_text = (
            "Canva proved that product discovery drives enterprise growth. "
            "Founders must close their first 10 customers personally [1]."
        )

        audit = verify_essay_grounding(text=essay_text, evidence_entries=[evidence], topic="Founder Sales")
        assert audit["is_grounded"] is False
        assert "Canva" in audit["unsupported_companies"]

    def test_valid_citation_index_does_not_establish_substantive_claim_support(self):
        """A syntactically valid citation index does not prevent detection of unsupported claims."""
        citation = _mock_citation(
            content="Founders should close their first 10 customers themselves before hiring sales reps."
        )
        evidence = EvidenceEntry(
            index=1,
            source=citation,
            header=f"Episode: {citation.episode_title}",
            excerpt=citation.content,
        )

        # Cites [1] (which is a valid index), but asserts an unsupported timeline
        essay_text = "Founders should secure 10 customers within their first 100 days [1]."

        # Citation reconciler accepts [1] as valid index
        sanitized, valid_cited, invalid_cited = reconcile_and_sanitize_essay_citations(
            text=essay_text,
            evidence_entries=[evidence],
        )
        assert 1 in valid_cited
        assert len(invalid_cited) == 0

        # But grounding audit correctly detects the ungrounded timeline
        audit = verify_essay_grounding(text=sanitized, evidence_entries=[evidence], topic="Founder Sales")
        assert audit["is_grounded"] is False
        assert any("100 days" in m for m in audit["unsupported_metrics"])

    @pytest.mark.asyncio
    async def test_orchestrator_honest_partial_status_and_diagnostic_on_grounding_issue(self, db_session: Session):
        """Orchestrator sets partial status, includes diagnostic advisory, and preserves content/persistence."""
        session = create_session(db=db_session, title="Grounding Audit Session")
        citation = _mock_citation(
            content="Founders should close their first 10 customers themselves before hiring sales reps."
        )
        mock_retrieval = MagicMock()
        mock_retrieval.retrieve.return_value = RetrievalResponse(
            query="Founder sales",
            status="success",
            items=[citation],
            coverage=_mock_coverage(),
            disclaimer=None,
        )

        mock_pi = AsyncMock()
        mock_outline = (
            "TITLE: Master Founder-Led Sales Discovery\n"
            "AUDIENCE: SaaS Founders\n"
            "HOOK: Why automation fails early.\n"
            "THESIS: Close early customers yourself.\n"
            "SECTION 1: Core Tension | PURPOSE: Hook | EVIDENCE: [1]\n"
            "SECTION 2: Ground Rules | PURPOSE: Rules | EVIDENCE: [1]\n"
            "SECTION 3: Playbook | PURPOSE: Tactics | EVIDENCE: [1]\n"
            "SECTION 4: Common Traps | PURPOSE: Pitfalls | EVIDENCE: [1]\n"
            "SECTION 5: Action Steps | PURPOSE: Checklist | EVIDENCE: [1]\n"
            "TAKEAWAY: Master discovery first.\n"
        )

        # Section body contains unsupported timeline "first 100 days" and ungrounded "Canva"
        sec_body = (
            "Founders often believe that automating sales will accelerate early traction. "
            "However, early selling is an exercise in customer discovery, not mechanical execution [1]. "
            "Canva achieved virality, but SaaS founders face enterprise procurement realities. "
            "Founders should secure 10 customers within their first 100 days to establish proof [1]. "
            "Personal discovery calls reveal pricing friction and product gaps directly. "
            "Founders must handle the earliest sales pipeline personally before delegating.\n\n"
            "- Personally conduct every demo until ten accounts close.\n"
            "- Document buyer triggers in a shared repository.\n"
            "- Refine positioning weekly based on direct feedback.\n\n"
            "Sustainable go-to-market execution requires founder immersion."
        )

        mock_pi.generate_response.side_effect = [
            PiGenerationResult(text=mock_outline, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Core Tension\n\n{sec_body}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Ground Rules\n\n{sec_body}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Playbook\n\n{sec_body}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Common Traps\n\n{sec_body}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Action Steps\n\n{sec_body}\n\nThe Bottom Line: Master discovery before delegating.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        ]

        orchestrator = Ship30EssayOrchestrator(
            pi_client=mock_pi,
            retrieval_service=mock_retrieval,
        )

        res = await orchestrator.generate_essay(
            session_id=session.id,
            topic="Founder-led sales",
            audience="SaaS Founders",
            db=db_session,
        )

        # Honest partial status due to grounding defects
        assert res.status == "partial"
        assert res.disclaimer is not None
        assert "Grounding Advisory" in res.disclaimer
        # Markdown and YouTube sources are preserved
        assert "### Sources" in res.content
        assert len(res.citations) >= 1
        # Persistence has partial status and grounding audit recorded
        msgs, total = list_messages_by_session(db=db_session, session_id=session.id)
        assert total == 2
        assistant_msg = msgs[1]
        assert assistant_msg.source_metadata["status"] == "partial"
        assert assistant_msg.source_metadata["grounding_audit"]["is_grounded"] is False
        assert len(assistant_msg.source_metadata["grounding_audit"]["unsupported_metrics"]) > 0

    @pytest.mark.asyncio
    async def test_orchestrator_normal_completion_when_all_grounding_checks_pass(self, db_session: Session):
        """Orchestrator completes normally with completed status when all evidence checks pass."""
        session = create_session(db=db_session, title="Clean Grounding Session")
        citation = _mock_citation(
            content="Founders should close their first 10 customers themselves before hiring sales reps."
        )
        mock_retrieval = MagicMock()
        mock_retrieval.retrieve.return_value = RetrievalResponse(
            query="Founder sales",
            status="success",
            items=[citation],
            coverage=_mock_coverage(),
            disclaimer=None,
        )

        mock_pi = AsyncMock()
        mock_outline = (
            "TITLE: Why Founders Must Close Their First Customers Personally\n"
            "AUDIENCE: SaaS Founders\n"
            "HOOK: The dangerous trap of early sales delegation.\n"
            "THESIS: Direct discovery drives product-market fit.\n"
            "SECTION 1: Core Tension | PURPOSE: Hook | EVIDENCE: [1]\n"
            "SECTION 2: Ground Rules | PURPOSE: Rules | EVIDENCE: [1]\n"
            "SECTION 3: Playbook | PURPOSE: Tactics | EVIDENCE: [1]\n"
            "SECTION 4: Common Traps | PURPOSE: Pitfalls | EVIDENCE: [1]\n"
            "SECTION 5: Action Steps | PURPOSE: Checklist | EVIDENCE: [1]\n"
            "TAKEAWAY: Master discovery first.\n"
        )

        # Section body strictly adheres to evidence (uses supported "10 customers", no ungrounded companies or quotes)
        # Sized so that 5 sections land cleanly in the 1100-1400 word range
        sec_body = (
            "Founders often believe that deploying automated sales will immediately solve their pipeline generation problems. "
            "However, early selling is fundamentally an exercise in customer discovery, not mechanical scaling [1]. "
            "When you deploy sales reps prematurely, you sever the vital feedback loop between the market and product engineering. "
            "Every customer discovery call reveals subtle pricing objections, unexpected feature requests, and messaging friction. "
            "Jason Lemkin emphasizes that closing your first ten paying customers yourself is completely non-negotiable [1]. "
            "Until ten customers have signed actual contracts and wired payments, you do not have a validated sales playbook to automate. "
            "Direct immersion enables the founding team to refine the ideal customer profile rapidly.\n\n"
            "- Personally conduct every customer demo until ten paying accounts close.\n"
            "- Document the exact sequence of buyer questions and purchase triggers.\n"
            "- Map out customer onboarding steps before automating pipeline generation.\n\n"
            "Many early-stage software founders find customer discovery uncomfortable and seek to delegate it away. "
            "They see automated playbooks and think they can bypass the painful work of customer objection handling. "
            "This is an expensive misunderstanding of what operational tools do well. "
            "Structured workflows are powerful force multipliers for existing, validated playbooks with high conversion rates. "
            "They are not product strategists capable of diagnosing why an early prototype is failing to convert.\n\n"
            "Early sales discovery cannot be outsourced or delegated without losing strategic nuance [1]. "
            "Jason Lemkin reminds operators that customer objections provide the clearest signals for product refinement. "
            "By staying close to early buyers, founding teams uncover genuine willingness to pay and establish realistic positioning. "
            "Rushing to scale before proving customer traction consistently leads to wasted capital and misaligned roadmaps. "
            "True leverage emerges only after the foundational value proposition has been validated across real commercial conversations.\n\n"
            "Sustainable go-to-market execution requires direct founder involvement. "
            "When founders handle early pipeline personally, unit economics stabilize. "
            "Every customer conversation informs product roadmap decisions directly."
        )

        mock_pi.generate_response.side_effect = [
            PiGenerationResult(text=mock_outline, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Core Tension\n\n{sec_body}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Ground Rules\n\n{sec_body}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Playbook\n\n{sec_body}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Common Traps\n\n{sec_body}", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=f"## Action Steps\n\n{sec_body}\n\nThe Bottom Line: Master discovery before hiring.", provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
        ]

        orchestrator = Ship30EssayOrchestrator(
            pi_client=mock_pi,
            retrieval_service=mock_retrieval,
        )

        res = await orchestrator.generate_essay(
            session_id=session.id,
            topic="Founder sales according to Jason Lemkin",
            audience="SaaS Founders",
            db=db_session,
        )

        assert res.status == "completed"
        assert res.disclaimer is None or "Grounding Advisory" not in res.disclaimer
        assert len(res.citations) >= 1
        assert "### Sources" in res.content
        msgs, total = list_messages_by_session(db=db_session, session_id=session.id)
        assert total == 2
        assert msgs[1].source_metadata["status"] == "completed"
        assert msgs[1].source_metadata["grounding_audit"]["is_grounded"] is True


# ===========================================================================
# Targeted Tests: Quality, Topic Adherence, and Reliability Bug Fixes
# ===========================================================================


def test_strip_draft_artifacts_removes_imperative_drafting_instructions():
    """Verify detection and removal of imperative drafting directives and objective tags."""
    raw_draft = (
        "## Giving Away Your Legos\n\n"
        "Detail how leaders can apply Molly Graham's 'give away your legos' framework.\n\n"
        "Scaling a startup requires managers to continually surrender familiar responsibilities.\n\n"
        "- Provide a practical framework for delegating core duties.\n"
        "- Establish emotional readiness for organizational restructuring.\n\n"
        "Objective: Explain how leaders manage psychological resistance during headcount growth.\n\n"
        "Molly Graham emphasizes that rapid scaling feels like getting your legos taken away [1].\n\n"
        "Purpose: Concrete tactical advice for high-growth executive teams.\n\n"
        "When leaders embrace this transition, organizational leverage multiplies."
    )
    cleaned, detected = strip_draft_artifacts(raw_draft)
    assert len(detected) >= 4
    assert "Detail how leaders" not in cleaned
    assert "Provide a practical framework" not in cleaned
    assert "Objective:" not in cleaned
    assert "Purpose:" not in cleaned
    assert "Molly Graham emphasizes that rapid scaling" in cleaned
    assert "When leaders embrace this transition" in cleaned


def test_strip_draft_artifacts_preserves_legitimate_explanatory_prose_containing_keywords():
    """Verify that legitimate body sentences using phrases like 'detail how leaders' in prose are preserved."""
    legitimate_text = (
        "## Scaling Engineering Teams\n\n"
        "Recent management studies detail how leaders navigate rapid headcount expansion without losing culture [1].\n\n"
        "These operational playbooks provide a practical framework when hiring senior managers.\n\n"
        "Executive reviews explain how leaders maintain alignment during quarterly planning."
    )
    cleaned, detected = strip_draft_artifacts(legitimate_text)
    assert len(detected) == 0
    assert cleaned == legitimate_text.strip()
    assert "detail how leaders navigate" in cleaned
    assert "provide a practical framework when hiring" in cleaned
    assert "explain how leaders maintain" in cleaned


def test_strict_citation_integrity_when_no_inline_citations():
    """Verify that when no inline citations are cited, format_essay_sources returns empty and no ungrounded citations are attached."""
    evidence = [
        EvidenceEntry(
            index=1,
            source=_mock_citation(title="Molly Graham on Career Growth", guest="Molly Graham"),
            header="[1] Episode: Molly Graham on Career Growth",
            excerpt="Give away your legos as the team doubles.",
        ),
        EvidenceEntry(
            index=2,
            source=_mock_citation(title="Scaling Organizations", guest="Molly Graham"),
            header="[2] Episode: Scaling Organizations",
            excerpt="Embrace the discomfort of giving away your job every six months.",
        ),
    ]

    # Empty cited_indices must return empty string (never fallback to all evidence entries)
    sources_text = format_essay_sources(evidence_entries=evidence, cited_indices=[])
    assert sources_text == ""


@pytest.mark.asyncio
async def test_failed_sections_omitted_without_purpose_leakage_or_fabricated_content(db_session: Session):
    """Verify that when section drafting fails, purpose instructions are not injected, sections are omitted cleanly, and status is partial."""
    session = create_session(db=db_session, title="Partial Omission Test")
    mock_retrieval_svc = MagicMock(spec=SemanticRetrievalService)
    citation = _mock_citation(title="Career Growth", guest="Molly Graham")
    mock_retrieval_svc.retrieve.return_value = RetrievalResponse(
        query="Molly Graham career growth",
        status="success",
        items=[citation],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    mock_outline = (
        "TITLE: Giving Away Your Legos: Molly Graham's Career Growth Playbook\n"
        "THESIS: Sustainable leadership growth requires actively delegating your job every six months.\n"
        "SECTION 1: The Psychology of Growth | PURPOSE: Detail how leaders navigate the fear of delegation | EVIDENCE: [1]\n"
        "SECTION 2: The Six-Month Cycle | PURPOSE: Provide a practical framework for role evolution | EVIDENCE: [1]\n"
        "SECTION 3: Building Trust | PURPOSE: Explain how to train successors without micromanagement | EVIDENCE: [1]\n"
        "SECTION 4: Organizational Traps | PURPOSE: Detail failure modes when founders hoard tasks | EVIDENCE: [1]\n"
        "SECTION 5: The Growth Checklist | PURPOSE: Summarize concrete next steps | EVIDENCE: [1]\n"
    )

    valid_sec1 = (
        "## The Psychology of Growth\n\n"
        "Molly Graham observes that scaling a startup forces leaders to confront the discomfort of giving away their legos [1]. "
        "When an organization doubles in size, tasks that defined your initial role must be transitioned to newer team members. "
        "Resisting this transition creates severe operational bottlenecks across engineering and product teams.\n\n"
        "- Acknowledge emotional friction when transferring ownership of core systems.\n"
        "- Redefine personal success around team velocity rather than individual contribution.\n"
        "- Proactively train incoming leads before responsibilities become overwhelming."
    )

    mock_pi = MagicMock(spec=PiClient)
    # Stage 1 succeeds, Section 1 succeeds, Sections 2-5 fail/timeout
    mock_pi.generate_response = AsyncMock(
        side_effect=[
            PiGenerationResult(text=mock_outline, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiGenerationResult(text=valid_sec1, provider="ollama", model="qwen2.5:1.5b", raw_events=[]),
            PiTimeoutError("Section 2 timed out"),
            PiTimeoutError("Section 3 timed out"),
            PiTimeoutError("Section 4 timed out"),
            PiTimeoutError("Section 5 timed out"),
        ]
    )

    orchestrator = Ship30EssayOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval_svc,
        total_timeout_seconds=600,
        section_timeout_seconds=120,
    )

    res = await orchestrator.generate_essay(
        session_id=session.id,
        topic="Molly Graham career growth and giving away your legos",
        db=db_session,
    )

    # Truthful partial reporting
    assert res.status == "partial"
    assert "Giving Away Your Legos" in res.title
    assert "The Psychology of Growth" in res.content
    assert "[1]" in res.content
    assert "### Sources" in res.content

    # Planning directives and purposes must NOT appear in final essay content
    assert "Detail how leaders navigate the fear of delegation" not in res.content
    assert "Provide a practical framework for role evolution" not in res.content
    assert "Detail failure modes when founders hoard tasks" not in res.content
    assert "As discussed in Lenny's Podcast, execution discipline" not in res.content
    assert "execution rigor and validated milestones" not in res.content

    # Advisory disclaimer must explain the omitted sections truthfully
    assert res.disclaimer is not None
    assert "Partial Draft Notice: 4 planned section(s)" in res.disclaimer
    assert "The Six-Month Cycle" in res.disclaimer

    # Citations attached must only be those actually cited in valid content
    assert len(res.citations) == 1


def test_outline_and_section_prompts_enforce_topic_adherence():
    """Verify that outline and section prompts contain topic adherence mandates to prevent generic drift."""
    evidence = [
        EvidenceEntry(
            index=1,
            source=_mock_citation(title="Molly Graham Career Growth", guest="Molly Graham"),
            header="[1] Episode: Molly Graham Career Growth",
            excerpt="Give away your legos continually.",
        )
    ]

    outline_prompt = build_outline_prompt(
        topic="Molly Graham's career-growth insights",
        audience="Product Leaders",
        evidence_entries=evidence,
    )
    assert "CRITICAL TOPIC ADHERENCE MANDATE" in outline_prompt
    assert "Molly Graham's career-growth insights" in outline_prompt
    assert "DO NOT drift into generic startup topics" in outline_prompt

    section_prompt = build_section_prompt(
        section_index=2,
        total_sections=5,
        heading="The Six-Month Delegation Cycle",
        purpose="Explain how managers relinquish duties every six months",
        target_words=260,
        topic="Molly Graham's career-growth insights",
        audience="Product Leaders",
        evidence_entries=evidence,
    )
    assert "CRITICAL TOPIC ADHERENCE & GROUNDING MANDATE" in section_prompt
    assert "DO NOT echo or repeat the planning objective" in section_prompt
    assert "The Six-Month Delegation Cycle" in section_prompt


def test_fallback_outline_anchored_to_requested_topic():
    """Verify that fallback outline sections anchor to the requested topic rather than generic SaaS tropes."""
    orchestrator = Ship30EssayOrchestrator(pi_client=MagicMock(spec=PiClient))
    title, thesis, sections = orchestrator._parse_outline_response(
        outline_text="Malformed outline without proper section markers",
        topic="Molly Graham career growth",
        audience="Product Leaders",
    )
    assert len(sections) == 5
    # Headings must be tied to the topic
    assert any("Molly Graham career growth" in h for h, _ in sections)
    # Purposes must also anchor to the topic
    assert any("Molly Graham career growth" in p for _, p in sections)


