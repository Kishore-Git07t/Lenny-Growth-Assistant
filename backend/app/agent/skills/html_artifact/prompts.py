"""Prompt templates and parsing utilities for AI-generated HTML/CSS artifacts."""

import re
from typing import List, Optional, Tuple

from backend.app.agent.rag import EvidenceEntry

# Maximum allowed character length for raw model output to protect memory
MAX_ARTIFACT_OUTPUT_CHARS = 100_000


def build_artifact_prompt(
    user_prompt: str,
    title: Optional[str] = None,
    artifact_type: Optional[str] = None,
    style_preferences: Optional[str] = None,
    evidence_entries: Optional[List[EvidenceEntry]] = None,
) -> str:
    """Build comprehensive prompt instructing Pi Coding Agent to generate clean HTML/CSS.

    Args:
        user_prompt: Detailed user requirement description.
        title: Optional proposed title.
        artifact_type: Category (e.g. landing_page, dashboard, announcement, component).
        style_preferences: Visual style direction.
        evidence_entries: Grounded podcast evidence to weave into copy if applicable.

    Returns:
        Formatted prompt string.
    """
    category_label = (artifact_type or "landing_page").replace("_", " ").title()
    style_label = style_preferences or "modern, responsive, professional"

    evidence_context = ""
    if evidence_entries:
        passages = []
        for entry in evidence_entries:
            passages.append(
                f"[{entry.index}] Episode: \"{entry.source.episode_title}\""
                f"{f', Guest: {entry.source.guest_name}' if entry.source.guest_name else ''}\n"
                f"Excerpt: {entry.excerpt}"
            )
        evidence_context = (
            "\n\n### Grounded Lenny's Podcast Evidence:\n"
            "Use the following real insights, benchmarks, and advice in your copy where relevant:\n"
            + "\n\n".join(passages)
            + "\n\nIncorporate authentic terminology and learnings from these experts into your headlines and sections."
        )

    title_hint = f"\nSuggested Title: {title}" if title else ""

    return (
        f"You are an expert full-stack design technologist generating a production-quality "
        f"HTML and CSS artifact for a {category_label}.\n\n"
        f"### User Request:\n{user_prompt}\n"
        f"{title_hint}\n"
        f"Category: {category_label}\n"
        f"Visual Direction: {style_label}\n"
        f"{evidence_context}\n\n"
        f"### Mandatory Output Specifications:\n"
        f"1. Produce TWO distinct markdown code blocks: one for HTML and one for CSS.\n"
        f"2. Format your response exactly as follows:\n"
        f"TITLE: <Clean descriptive title for this artifact>\n"
        f"```html\n"
        f"<!-- Complete, standalone HTML fragment or document body -->\n"
        f"```\n"
        f"```css\n"
        f"/* Complete responsive CSS rules for this artifact */\n"
        f"```\n\n"
        f"### Design Quality & Responsive Standards:\n"
        f"- Structure: Use clean semantic HTML5 (<header>, <nav>, <main>, <section>, <article>, <figure>, <footer>).\n"
        f"- Layout: Use Flexbox and CSS Grid. Must be fully responsive with mobile @media queries.\n"
        f"- Typography: Use modern system font stacks (-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif) with clear hierarchical sizing.\n"
        f"- Components: Include realistic, visually compelling cards, badges, buttons, stat grids, or navigation.\n"
        f"- Colors & Contrast: Use harmonious palettes with accessible contrast. Do not force dark mode unless requested.\n"
        f"- Aesthetics: Use tasteful spacing, subtle borders, soft box-shadows, and smooth transitions.\n\n"
        f"### Truthful Content & No Fabricated Marketing Claims (MANDATORY):\n"
        f"- DO NOT invent customer counts, adoption metrics, or user numbers (e.g. '50+ AI Deployments', '10,000+ users').\n"
        f"- DO NOT invent revenue statistics, ARR figures, or conversion percentages.\n"
        f"- DO NOT invent official partnerships, certifications, or endorsements (e.g. 'OpenAI & Google Best Practices').\n"
        f"- DO NOT invent software release versions or false compliance badges (e.g. 'v3.2 Enterprise').\n"
        f"- Unless explicitly supplied by the user or supported by verified podcast transcript evidence, use neutral product benefit copy or clearly designated sample placeholders (e.g. '[Metric Placeholder]').\n\n"
        f"### Security & Static Constraints (CRITICAL):\n"
        f"- DO NOT include any <script> tags or JavaScript.\n"
        f"- DO NOT include inline JS event handlers (no onclick, onload, etc.).\n"
        f"- DO NOT include <iframe>, <object>, <embed>, or <form> elements.\n"
        f"- DO NOT include <svg> or <math> elements (use CSS badges/shapes or standard text/unicode symbols).\n"
        f"- DO NOT include remote @import statements or remote url() network imports in CSS.\n"
        f"- DO NOT include external image links or remote fonts (use system fonts and CSS styling).\n"
        f"- Output clean, static, safe HTML and CSS ONLY."
    )


def parse_model_artifact_output(
    raw_text: str,
    default_title: Optional[str] = None,
) -> Tuple[str, str, str, str]:
    """Parse Pi Coding Agent response into title, description, HTML, and CSS.

    Args:
        raw_text: Raw output string from model.
        default_title: Fallback title if model did not specify one.

    Returns:
        Tuple of (title, description, html_code, css_code).
    """
    if not raw_text or not raw_text.strip():
        return (default_title or "Generated Artifact", "", "", "")

    # Bound text length to prevent memory saturation
    text = raw_text[:MAX_ARTIFACT_OUTPUT_CHARS].strip()

    # 1. Extract title if specified (e.g. TITLE: My Landing Page)
    title = default_title or "Generated Artifact"
    title_match = re.search(r"^(?:TITLE|Title)\s*:\s*(.+)$", text, re.MULTILINE)
    if title_match:
        candidate_title = title_match.group(1).strip()
        candidate_title = re.sub(r"^[*_`\"'#\s]+|[*_`\"'#\s]+$", "", candidate_title).strip()
        if candidate_title:
            title = candidate_title

    # 2. Extract HTML block (```html ... ```)
    html_code = ""
    html_match = re.search(r"```html\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    if html_match:
        html_code = html_match.group(1).strip()
    else:
        # Fallback: check for generic code block containing html tags
        generic_blocks = re.findall(r"```(?:xml)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
        for block in generic_blocks:
            if "<div" in block.lower() or "<section" in block.lower() or "<header" in block.lower():
                html_code = block.strip()
                break

    # 3. Extract CSS block (```css ... ```)
    css_code = ""
    css_match = re.search(r"```css\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    if css_match:
        css_code = css_match.group(1).strip()
    else:
        # Fallback: check for generic block with CSS syntax
        generic_blocks = re.findall(r"```\s*\n(.*?)\n```", text, re.DOTALL)
        for block in generic_blocks:
            if "{" in block and "}" in block and ":" in block and not block.strip().startswith("<"):
                css_code = block.strip()
                break

    # 4. Extract any inline <style> block if HTML mistakenly contains one
    if not css_code and "<style" in html_code.lower():
        style_match = re.search(r"<style[^>]*>(.*?)</style>", html_code, re.DOTALL | re.IGNORECASE)
        if style_match:
            css_code = style_match.group(1).strip()
            html_code = re.sub(r"<style[^>]*>.*?</style>", "", html_code, flags=re.DOTALL | re.IGNORECASE).strip()

    # 5. Extract brief description from text preceding code blocks
    first_fence = text.find("```")
    preamble = text[:first_fence].strip() if first_fence != -1 else ""
    desc_lines = []
    for line in preamble.splitlines():
        clean_l = line.strip()
        if clean_l and not clean_l.upper().startswith("TITLE:"):
            desc_lines.append(clean_l)
    description = " ".join(desc_lines[:2]) if desc_lines else f"Visual layout for {title}"

    return title, description, html_code, css_code


def generate_fallback_artifact(
    prompt: str,
    title: Optional[str] = None,
    artifact_type: Optional[str] = None,
) -> Tuple[str, str, str]:
    """Generate high-quality, responsive fallback HTML and CSS if model generation fails.

    Returns:
        Tuple of (title, html, css).
    """
    safe_title = title or "Growth Strategy Artifact"
    cat = (artifact_type or "growth_showcase").replace("_", " ").title()

    html = f"""<div class="artifact-container">
  <header class="artifact-header">
    <div class="artifact-badge">{cat}</div>
    <h1 class="artifact-title">{safe_title}</h1>
    <p class="artifact-subtitle">Tailored visual layout generated from growth principles and execution insights.</p>
  </header>

  <main class="artifact-grid">
    <section class="artifact-card">
      <div class="card-icon">01</div>
      <h2>Strategic Alignment</h2>
      <p>Clarify core value proposition and focus direct founder attention on early customer discovery and validation.</p>
    </section>

    <section class="artifact-card featured">
      <div class="card-icon">02</div>
      <h2>Execution Rigor</h2>
      <p>Establish quantifiable milestones and validate unit economics before scaling automation or outbound pipelines.</p>
    </section>

    <section class="artifact-card">
      <div class="card-icon">03</div>
      <h2>Feedback Loops</h2>
      <p>Document every user objection to inform roadmap decisions and iterate go-to-market positioning rapidly.</p>
    </section>
  </main>

  <footer class="artifact-footer">
    <div class="cta-banner">
      <h3>Ready to accelerate execution?</h3>
      <p>Review key operational thresholds and prioritize customer discovery.</p>
      <button type="button" class="cta-button">Explore Insights</button>
    </div>
  </footer>
</div>"""

    css = """/* Responsive Artifact Stylesheet */
:root {
  --primary: #4f46e5;
  --primary-hover: #4338ca;
  --bg-surface: #ffffff;
  --bg-card: #f9fafb;
  --text-main: #111827;
  --text-muted: #6b7280;
  --border: #e5e7eb;
}

.artifact-container {
  max-width: 1000px;
  margin: 0 auto;
  padding: 2rem 1rem;
  color: var(--text-main);
}

.artifact-header {
  text-align: center;
  margin-bottom: 3rem;
}

.artifact-badge {
  display: inline-block;
  padding: 0.25rem 0.75rem;
  background-color: #e0e7ff;
  color: var(--primary);
  border-radius: 9999px;
  font-size: 0.875rem;
  font-weight: 600;
  margin-bottom: 1rem;
}

.artifact-title {
  font-size: 2.25rem;
  font-weight: 800;
  letter-spacing: -0.025em;
  margin-bottom: 0.75rem;
  color: var(--text-main);
}

.artifact-subtitle {
  font-size: 1.125rem;
  color: var(--text-muted);
  max-width: 600px;
  margin: 0 auto;
}

.artifact-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1.5rem;
  margin-bottom: 3rem;
}

.artifact-card {
  background-color: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 0.75rem;
  padding: 1.75rem;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.artifact-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05);
}

.artifact-card.featured {
  background-color: #ffffff;
  border-color: var(--primary);
  box-shadow: 0 4px 6px -1px rgba(79, 70, 229, 0.1);
}

.card-icon {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--primary);
  margin-bottom: 1rem;
}

.artifact-card h2 {
  font-size: 1.25rem;
  font-weight: 700;
  margin-bottom: 0.5rem;
}

.artifact-card p {
  color: var(--text-muted);
  font-size: 0.95rem;
  line-height: 1.6;
}

.artifact-footer {
  margin-top: 2rem;
}

.cta-banner {
  background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%);
  color: #ffffff;
  padding: 2.5rem;
  border-radius: 1rem;
  text-align: center;
}

.cta-banner h3 {
  font-size: 1.5rem;
  font-weight: 700;
  margin-bottom: 0.5rem;
}

.cta-banner p {
  color: #e0e7ff;
  margin-bottom: 1.5rem;
}

.cta-button {
  background-color: #ffffff;
  color: var(--primary);
  border: none;
  padding: 0.75rem 1.75rem;
  border-radius: 0.5rem;
  font-weight: 600;
  font-size: 1rem;
  cursor: pointer;
  transition: background-color 0.2s ease;
}

.cta-button:hover {
  background-color: #f3f4f6;
}

@media (max-width: 640px) {
  .artifact-title {
    font-size: 1.75rem;
  }
  .artifact-grid {
    grid-template-columns: 1fr;
  }
  .cta-banner {
    padding: 1.5rem;
  }
}"""

    return safe_title, html, css
