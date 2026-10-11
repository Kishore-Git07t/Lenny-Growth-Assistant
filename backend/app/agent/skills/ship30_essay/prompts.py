"""Prompt generation and templating for Ship 30 for 30 essay generation."""

from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.app.agent.rag import EvidenceEntry, extract_cited_indices

SKILL_DIR = Path(__file__).parent
SKILL_MD_PATH = SKILL_DIR / "SKILL.md"


def is_duplicate_title(candidate: str, title: Optional[str]) -> bool:
    """Check if candidate heading duplicates or substantially restates the title."""
    if not candidate or not title:
        return False
    c_clean = re.sub(r"[^\w\s]", "", candidate.lower()).strip()
    t_clean = re.sub(r"[^\w\s]", "", title.lower()).strip()
    if not c_clean or not t_clean:
        return False
    if c_clean == t_clean:
        return True
    # Substantial containment check (e.g. if one contains the other and length ratio > 0.65)
    min_len = min(len(c_clean), len(t_clean))
    max_len = max(len(c_clean), len(t_clean))
    if (t_clean in c_clean or c_clean in t_clean) and (min_len / max_len > 0.65):
        return True
    # Word set overlap check
    c_words = set(c_clean.split())
    t_words = set(t_clean.split())
    if c_words and t_words:
        overlap = len(c_words & t_words) / max(1, min(len(c_words), len(t_words)))
        if overlap >= 0.85 and min(len(c_words), len(t_words)) >= 4:
            return True
    return False


def load_skill_instructions() -> str:
    """Read the Ship 30 for 30 skill instructions from SKILL.md."""
    if SKILL_MD_PATH.exists():
        try:
            return SKILL_MD_PATH.read_text(encoding="utf-8")
        except Exception:
            pass
    return (
        "Ship 30 for 30 Digital Writing Principles:\n"
        "- Clear over clever headlines tailored to a specific reader.\n"
        "- 1-3-1 opening hook presenting immediate tension.\n"
        "- Single coherent direction with informative H2 headings.\n"
        "- Varied sentence rhythms, readable bullets, selective bolding.\n"
        "- Highly practical, evidence-backed advice with clear closing takeaway."
    )


def count_words(text: str) -> int:
    """Accurately count words in a Markdown document.

    Strips code fences, HTML tags, and markdown links to count true textual words.
    """
    if not text:
        return 0
    # Strip markdown code blocks
    stripped = re.sub(r"```[\s\S]*?```", "", text)
    # Strip HTML tags
    stripped = re.sub(r"<[^>]+>", "", stripped)
    tokens = stripped.split()
    return len(tokens)


def _format_evidence_item(entry: EvidenceEntry) -> str:
    """Format an EvidenceEntry for prompt inclusion clearly without encouraging header copying."""
    content = getattr(entry, "excerpt", "") or (entry.source.content if hasattr(entry, "source") and entry.source else "")
    guest = getattr(entry.source, "guest_name", None) if hasattr(entry, "source") and entry.source else None
    guest_part = f", Guest: {guest}" if guest else ""
    ep_title = getattr(entry.source, "episode_title", "Lenny's Podcast") if hasattr(entry, "source") and entry.source else "Lenny's Podcast"
    return f"Source [{entry.index}] | Episode: \"{ep_title}\"{guest_part}\nTranscript excerpt:\n\"{content}\""


def build_outline_prompt(
    topic: str,
    audience: str,
    evidence_entries: List[EvidenceEntry],
) -> str:
    """Build the Stage 1 prompt to generate the structured essay outline."""
    evidence_text = "\n\n".join(
        _format_evidence_item(entry)
        for entry in evidence_entries
    )

    return f"""You are an elite digital writer specializing in the Ship 30 for 30 framework and product growth strategy.

TASK: Create a structured outline for a ~1,250-word digital essay grounded strictly in authentic transcript evidence from Lenny's Podcast.

TOPIC: {topic}
TARGET READER: {audience}

--- AVAILABLE VERIFIED PODCAST EVIDENCE ---
{evidence_text}

--- CRITICAL TOPIC ADHERENCE MANDATE ---
Every single section, argument, and takeaway MUST directly explore and answer the exact topic: "{topic}".
- If the topic specifies a particular guest (e.g. Molly Graham, Jason Lemkin, Elena Verna), framework (e.g. "giving away your legos", "freemium vs trial", "sales hiring thresholds"), or operational domain (e.g. career growth, scaling organizations), the outline MUST be firmly anchored to that specific person's insights and that framework.
- DO NOT drift into generic startup topics, founder personality psychology, or unrelated management clichés.
- Ensure all 5 section titles and objectives explicitly tie back to "{topic}".

--- SHIP 30 FOR 30 DIGITAL WRITING PRINCIPLES ---
1. Clear Over Clever Headline: Create a concise, natural, punchy title (6 to 10 words) tailored to {audience}.
   - State an explicit benefit, counter-intuitive insight, or clear outcome.
   - Do NOT use generic prefixes like "The Operator's Playbook:" or repeat the raw prompt question.
   - Example styles:
     * "Why Early-Stage SaaS Founders Must Not Outsource Sales"
     * "When Early-Stage Founders Should Hire Sales vs Automate"
     * "AI Sales Agents: What Founders Must Know Before Automating"
2. Opening Hook: 1-3-1 structure establishing immediate friction or a counter-intuitive dilemma.
3. Core Thesis: One bold argument backed by verified transcript evidence.
4. Structure: Plan exactly 5 distinct sections (~250 words each) with informative, distinctive H2 headings:
   - Section 1: Opening Hook, Core Dilemma & Central Thesis (~230 words)
     (Do NOT repeat the essay title as the Section 1 heading; use a distinct operational heading like 'The Core Tension & Strategic Dilemma')
   - Section 2: Foundational Principle & Strategic Milestones (~260 words)
   - Section 3: Tactical Execution Playbook & Mechanics (~260 words)
   - Section 4: Dangerous Traps & Counter-Intuitive Realities (~260 words)
   - Section 5: Action Checklist & 30-Day Decision Framework (~240 words)
5. Closing Takeaway: A memorable, 1-sentence bottom-line synthesis.

VOICE AND PERSPECTIVE:
- Write in an authoritative, objective editorial voice tailored to {audience}.
- NEVER use the first-person singular ("I", "me", "my", "as a founder I often wonder").
- NEVER impersonate podcast guests or Lenny Rachitsky.
- NEVER invent fictitious personal founder experiences or ungrounded startup anecdotes.

STRICT FACTUAL GROUNDING & EVIDENCE FIDELITY:
- Ground all outline sections strictly in the VERIFIED PODCAST EVIDENCE provided above.
- ONLY cite facts, metrics, companies, and quotes present in the evidence. Reference evidence entries with [1], [2], etc.
- NUMERICAL SPECIFICITY: NEVER invent artificial timelines (e.g., 'within their first 100 days', '6 months'), arbitrary percentage allocations (e.g., 'devote 20% of time'), customer quotas, or ARR figures unless explicitly stated in the provided evidence. If the evidence provides a qualitative recommendation (e.g. 'close early customers yourself'), state it qualitatively; do NOT turn it into unsupported quantitative benchmarks.
- COMPANY EXAMPLES: NEVER inject external company case studies (e.g., Canva, Figma, Stripe, Airbnb) unless that company is explicitly named and discussed in the verified evidence above.
- DIRECT QUOTATIONS: Never invent direct quotations or put manufactured words in quotation marks. If paraphrasing, write in objective editorial prose without quotation marks.
- ATTRIBUTION: Distinguish transcript evidence from editorial analysis. A citation marker like [1] must directly support the specific assertion it follows.
- NEVER invent guest titles, credentials, or professional histories.
- NEVER invent fictitious podcast episodes or reference citation numbers outside the provided evidence indices.
- NEVER include author notes, drafting commentary, or instructions like "Please replace them with...".

OUTPUT FORMAT:
Return your outline in this clean, structured format (keep it concise, under 200 words):
TITLE: <Concise, punchy 6-10 word title; no quotes, no asterisks, no question mark>
AUDIENCE: {audience}
HOOK: <Opening hook and core tension>
THESIS: <Central thesis statement>
SECTION 1: <Distinct H2 Heading; do NOT duplicate title> | PURPOSE: <Summary> | EVIDENCE: <e.g. [1]>
SECTION 2: <H2 Heading> | PURPOSE: <Summary> | EVIDENCE: <e.g. [1]>
SECTION 3: <H2 Heading> | PURPOSE: <Summary> | EVIDENCE: <e.g. [1]>
SECTION 4: <H2 Heading> | PURPOSE: <Summary> | EVIDENCE: <e.g. [1]>
SECTION 5: <H2 Heading> | PURPOSE: <Summary> | EVIDENCE: <e.g. [1]>
TAKEAWAY: <Final actionable conclusion>
"""


def build_section_prompt(
    section_index: int,
    total_sections: int,
    heading: str,
    purpose: str,
    target_words: int,
    topic: str,
    audience: str,
    evidence_entries: List[EvidenceEntry],
    previous_summary: Optional[str] = None,
) -> str:
    """Build the Stage 2 prompt to draft an individual section of the essay with an explicit word budget."""
    evidence_text = "\n\n".join(
        _format_evidence_item(entry)
        for entry in evidence_entries
    )

    prev_context = (
        f"\nPREVIOUS SECTION CONTEXT:\n{previous_summary}\n"
        if previous_summary
        else ""
    )

    is_intro = section_index == 1
    is_conclusion = section_index == total_sections

    role_instruction = ""
    if is_intro:
        role_instruction = (
            f"Start with '## {heading}'. Open with a punchy 1-3-1 hook "
            "that captures attention, defines the problem, and states the central thesis. "
            "Do NOT include a top-level # H1 title or repeat the article headline."
        )
    elif is_conclusion:
        role_instruction = (
            f"Start with '## {heading}'. This is the closing section. Provide a high-impact action checklist, "
            "synthesize key decision criteria, and finish with a memorable 1-sentence bottom-line takeaway."
        )
    else:
        role_instruction = (
            f"Start with '## {heading}'. Deliver actionable insights, operational mechanics, "
            "and a readable bullet list of key principles or steps."
        )

    max_words = target_words + 25

    return f"""You are a master digital writer executing the Ship 30 for 30 essay framework.

TASK: Write Section {section_index} of {total_sections} for a comprehensive digital essay.
TARGET WORD BUDGET: Aim for ~{target_words} words (target range: {target_words - 25} to {max_words} words; do not exceed {max_words} words).

TOPIC: {topic}
TARGET AUDIENCE: {audience}
SECTION HEADING: {heading}
SECTION OBJECTIVE: {purpose}
{prev_context}
--- VERIFIED PODCAST TRANSCRIPT EVIDENCE ---
{evidence_text}

--- CRITICAL TOPIC ADHERENCE & GROUNDING MANDATE ---
1. Strict Topic Adherence: Every sentence, paragraph, and bullet in this section MUST directly answer and explore the user's requested topic: "{topic}".
   - Do NOT drift into generic startup tropes, founder personality traits, or tangential topics.
   - Anchor all discussions in the specific guest frameworks and principles requested in "{topic}".
2. Section Scope: Fulfill the section heading ("{heading}") and section objective ("{purpose}") directly. DO NOT echo or repeat the planning objective, section purpose, or outline instructions in the finished prose.
3. {role_instruction}
4. Objective Editorial Voice: Write in an authoritative, objective third-person editorial voice tailored to {audience}. NEVER write in the first person singular ("I", "me", "my", "as a founder I often wonder"). NEVER impersonate the podcast speakers or Lenny Rachitsky. NEVER invent personal founder anecdotes.
5. No Scaffolding, Author Notes, or Planning Echoes:
   - DO NOT echo or repeat the planning objective, section purpose, or outline directives. NEVER write out phrases like "Detail how...", "Provide a practical framework...", "Explain how...", "In this section...", or "Objective:...".
   - Write ONLY polished, reader-facing publication prose. Do not include meta-commentary, placeholders, or author scaffolding.
6. Strict Factual Grounding & Evidence Safeguards: Ground all claims exclusively in the VERIFIED PODCAST TRANSCRIPT EVIDENCE above.
   - Grounded Metrics & Timelines: All numbers, customer counts, percentages, and timelines MUST originate directly from the verified transcript text above. NEVER invent arbitrary numbers, percentage splits (e.g. '20% of time'), or artificial timelines (e.g. 'first 100 days'). If the transcript speaks qualitatively, keep the recommendation qualitative.
   - Grounded Company Examples: NEVER introduce ungrounded company case studies (e.g. Canva, Figma, Stripe, Airbnb) unless explicitly mentioned in the verified evidence above.
   - Quotation Fidelity: Direct quotations inside quotation marks ("...") MUST be authentic, near-verbatim statements from the retrieved transcript. If paraphrasing or summarizing a speaker's perspective, integrate it into third-person editorial prose without quotation marks.
   - Honest Attribution: Distinguish transcript evidence from editorial interpretation. A citation tag (e.g. [1]) must strictly support the adjacent factual claim, never unrelated editorial commentary.
   - Use ONLY citation numbers that exist in the evidence above (e.g., [1], [2]). NEVER cite invented numbers like [5].
   - Place ONLY clean bracketed markers like [1] in prose. NEVER copy prompt metadata such as '(Episode: ...)' or 'Evidence: [N]'.
7. Varied Sentence Rhythm: Alternate 1-sentence punchy lines with 2-3 sentence explanations. Never write huge walls of text.
8. Skimmability: Use a formatted bullet list (- item) for core steps, symptoms, or criteria.
9. Bold Emphasis: Bold (**phrase**) the most critical 2-3 key insights.
10. Substantive Depth & Word Budget: Aim for ~{target_words} words (range: {target_words - 25} to {max_words} words).
   - Write 2 to 3 substantive, well-developed body paragraphs that thoroughly explain the operational mechanics and evidence.
   - Include 1 structured 3-to-4 item bullet list where each bullet point provides a complete, actionable principle with meaningful explanation.
   - GROUNDING FIRST: Never pad text with unsupported filler. If the transcript evidence on a specific point is concise, provide thorough editorial analysis of that evidence rather than fabricating external claims.
11. Output Format: Output clean, raw Markdown directly. Do NOT wrap your output in ```markdown or ``` code fences. Do NOT repeat the essay title as an H1 or H2. Do NOT insert podcast episode titles as headings.

Write the complete Markdown text for this section now:
"""


def normalize_editorial_voice(text: str) -> str:
    """Normalize accidental first-person personal anecdotes to objective editorial voice.

    Protects authentic transcript quotations within quotation marks so first-person
    language inside guest quotes is never altered.
    """
    if not text:
        return ""

    # Split into segments by double quotes or smart quotes to protect verbatim quotations
    segments = re.split(r'("[^"\n]*"|“[^”\n]*”)', text)

    def _replace_unquoted(s: str) -> str:
        # Common unsupported first-person founder openings
        s = re.sub(
            r"\bAs (?:the|a) founder of (?:a|an) [^,]+, I often wonder\b",
            "Early-stage SaaS founders often wonder",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r"\bAs (?:the|a) founder, I often\b",
            "Founders often",
            s,
            flags=re.IGNORECASE,
        )
        # Note: Do not place \b after a punctuation character like comma
        s = re.sub(
            r"\bIn my experience,\s*",
            "In practice, ",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r"\bIn my experience\b",
            "in practice",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r"\bIn our experience,\s*",
            "In practice, ",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r"\bIn our experience\b",
            "in practice",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r"\bI have found that\b",
            "Grounded evidence demonstrates that",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r"\bI believe that\b",
            "Evidence indicates that",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r"\bI recommend that\b",
            "Best practice recommends that",
            s,
            flags=re.IGNORECASE,
        )
        return s

    processed = []
    for idx, seg in enumerate(segments):
        # Odd indices (1, 3, 5...) are captured quoted strings
        if idx % 2 == 1:
            processed.append(seg)
        else:
            processed.append(_replace_unquoted(seg))

    return "".join(processed)


DRAFT_ARTIFACT_PATTERNS = [
    # "Please replace them with concrete key insights derived from Jason Lemkin's podcast."
    r"(?i)\bPlease replace\b[^\n.!?]*[.!?]?",
    # "Please insert...", "Please fill in...", "Please add...", "Please update...", "Please provide..."
    r"(?i)\bPlease (?:insert|fill in|add|update|provide)\b[^\n.!?]*[.!?]?",
    # "[insert evidence here]", "[insert ...]", "[fill in ...]", "[placeholder]"
    r"(?i)\[[ \t]*(?:insert|replace|fill in|todo|tbd|placeholder|evidence|source)[^\]\n]*\]",
    # "TODO: ...", "TBD: ...", "FIXME: ..."
    r"(?i)\b(?:TODO|TBD|FIXME)[ \t]*:[ \t]*[^\n]+",
    # "Note to author: ...", "Author's note: ...", "Drafting note: ...", "Editor's note: ..."
    r"(?i)\b(?:Note to author|Author's note|Drafting note|Editor's note)[ \t]*:[ \t]*[^\n]+",
    # Model meta-commentary: "In this draft, ...", "In this section, please ..."
    r"(?i)\bIn this draft,[ \t]*[^\n.!?]*[.!?]?",
    # Section directive tags: "Objective: ...", "Purpose: ...", "Drafting instructions: ..."
    r"(?im)^[ \t]*(?:[-*•][ \t]*)?(?:Objective|Purpose|Goal|Instructions?|Drafting instructions?)[ \t]*:[ \t]*[^\n]+",
    # Imperative drafting instructions and planning directives (at line or bullet start, e.g. "Detail how leaders...", "- Provide a practical framework...")
    r"(?im)^[ \t]*(?:[-*•][ \t]*)?(?:Detail how leaders\b|Detail how\b|Provide a practical framework\b|Provide a framework\b|Explain how leaders\b|Detail the framework\b)[^\n]*",
]


def strip_draft_artifacts(text: str) -> Tuple[str, List[str]]:
    """Detect and remove author notes, drafting instructions, and unfinished placeholders.

    Returns (cleaned_text, detected_artifacts).
    """
    if not text:
        return "", []

    detected: List[str] = []
    cleaned = text

    for pat in DRAFT_ARTIFACT_PATTERNS:
        matches = re.findall(pat, cleaned)
        if matches:
            for m in matches:
                detected.append(m.strip())
            cleaned = re.sub(pat, "", cleaned)

    # Clean up empty bullet lines or bullets that only contain punctuation
    cleaned = re.sub(r"(?m)^\s*[-*•]\s*$", "", cleaned)
    # Clean up empty lines or spaces left behind
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n\s*\n\s*\n+", "\n\n", cleaned)

    return cleaned.strip(), detected


def strip_metadata_leaks(text: str) -> Tuple[str, List[int]]:
    """Strip standalone and inline retrieval prompt metadata leaked into draft text.

    Removes:
    - Inline metadata trailers: `[1] (Episode: ... (SaaStr) ... )` -> `[1]`
    - Malformed fragments: `[1], Guest: Jason M Lemkin)` -> `[1]`
    - Standalone metadata lines: `[1] (Episode: ...)`, `- Evidence: [5] (...)`
    - Standalone `Evidence: [N]` tags
    - Standalone orphaned metadata lines like `[1], Guest: Jason M Lemkin)`

    Returns (cleaned_text, indices_found_in_stripped_metadata).
    """
    if not text:
        return "", []

    stripped_indices: List[int] = []

    # 1. Clean standalone metadata lines first
    lines = text.split("\n")
    kept_lines = []
    for line in lines:
        stripped = line.strip()

        # Matches standalone lines starting with bracketed citation and metadata headers/fragments:
        # e.g., "[1] (Episode: ...)", "[1], Guest: Jason M Lemkin)", "- Evidence: [5] (Podcast ...)"
        m_ev_line = re.match(
            r"^[-*]?\s*(?:Evidence|Source)?\s*:?\s*\[(\d+)\]\s*(?:\(?\s*(?:Episode|Podcast|Source|Lenny's Podcast)\b|,?\s*Guest:\s*).*$",
            stripped,
            re.IGNORECASE,
        )
        if m_ev_line:
            stripped_indices.append(int(m_ev_line.group(1)))
            continue

        # Matches standalone "Evidence: [1]" or "- Evidence: [1]"
        m_ev_tag = re.match(
            r"^[-*]?\s*Evidence\s*:\s*\[(\d+)\]\s*$",
            stripped,
            re.IGNORECASE,
        )
        if m_ev_tag:
            stripped_indices.append(int(m_ev_tag.group(1)))
            continue

        # Matches standalone orphaned metadata lines like "(Episode: ...)", "(Podcast: ...)", "Guest: Jason Lemkin)"
        if re.match(
            r"^[-*]?\s*\(?(?:Episode|Podcast|Source|Lenny's Podcast)\s*:.*$",
            stripped,
            re.IGNORECASE,
        ):
            continue

        if re.match(
            r"^[-*]?\s*Guest\s*:[^)\n]+(?:\)|$)",
            stripped,
            re.IGNORECASE,
        ):
            continue

        # Matches general standalone "Evidence: ..." line without bracket
        if re.match(r"^[-*]?\s*Evidence\s*:\s*.*?(?:podcast|episode|lenny).*?$", stripped, re.IGNORECASE):
            continue

        kept_lines.append(line)

    cleaned = "\n".join(kept_lines)

    # 2. Inline metadata trailer cleaner supporting nested parentheses like `(SaaStr)`
    # e.g. `[1] (Episode: We replaced our sales team ... (SaaStr), Guest: Jason Lemkin)` -> `[1]`
    cleaned = re.sub(
        r"\[(\d+)\]\s*\((?:Episode|Podcast|Source|Guest|Lenny's Podcast)(?:[^()\n]|\([^()\n]*\))*\)",
        r"[\1]",
        cleaned,
        flags=re.IGNORECASE,
    )

    # 3. Malformed inline fragments cleaner:
    # e.g. `[1], Guest: Jason M Lemkin)` or `[1] (Guest: Jason M Lemkin)` -> `[1]`
    cleaned = re.sub(
        r"\[(\d+)\]\s*,\s*Guest:\s*[^)\n]+(?:\)|(?=\s*[.,;:!?\n]|$))",
        r"[\1]",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\[(\d+)\]\s*\(\s*Guest:\s*[^)\n]+\)",
        r"[\1]",
        cleaned,
        flags=re.IGNORECASE,
    )

    # 4. Clean any residual standalone metadata lines that might have been unmasked
    final_lines = []
    for line in cleaned.split("\n"):
        stripped = line.strip()
        if re.match(r"^[-*]?\s*(?:Episode|Podcast|Source|Guest)\s*:[^)\n]*\)?$", stripped, re.IGNORECASE):
            continue
        final_lines.append(line)

    cleaned = "\n".join(final_lines)

    # Clean punctuation spacing left behind (e.g. "founders [1] ." -> "founders [1].")
    cleaned = re.sub(r"\[(\d+)\]\s+([.,;:!?])", r"[\1]\2", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)

    return cleaned, stripped_indices


def reconcile_and_sanitize_essay_citations(
    text: str,
    evidence_entries: List[EvidenceEntry],
) -> Tuple[str, List[int], List[int]]:
    """Reconcile inline citation markers against verified evidence entries.

    Guarantees:
    - Removes leaked prompt metadata (e.g. `[1] (Episode: ...)` -> `[1]`).
    - Detects all inline citation markers.
    - Strips unsupported / hallucinated citation markers (e.g. `[5]` when valid entries are 1..4).
    - Preserves legitimate numbered lists (e.g. `1.`, `2.`) and numerical expressions (e.g. `10 customers`).
    - Returns (sanitized_text, valid_cited_indices, invalid_cited_indices).
    """
    if not text:
        return "", [], []

    valid_indices = {entry.index for entry in evidence_entries}
    invalid_indices_found: List[int] = []

    # 1. Clean leaked prompt metadata lines and inline trailers
    cleaned, metadata_indices = strip_metadata_leaks(text)
    for m_idx in metadata_indices:
        if m_idx not in valid_indices and m_idx not in invalid_indices_found:
            invalid_indices_found.append(m_idx)

    # 2. Find and reconcile bracketed citation markers in the text
    # Negative lookahead (?!\s*\() ensures we don't match Markdown links [Anchor](url)
    def replace_bracket(match: re.Match) -> str:
        raw_content = match.group(1).strip()
        # Check if bracket contains digits (citations)
        if not re.search(r"\d+", raw_content):
            return match.group(0)

        # Extract citation numbers
        nums = extract_cited_indices(match.group(0))
        if not nums:
            return match.group(0)

        valid_nums = [n for n in nums if n in valid_indices]
        invalid_nums = [n for n in nums if n not in valid_indices]

        for inv in invalid_nums:
            if inv not in invalid_indices_found:
                invalid_indices_found.append(inv)

        if valid_nums:
            return f"[{', '.join(str(n) for n in valid_nums)}]"
        else:
            return ""

    sanitized = re.sub(r"\[([^\]]+)\](?!\s*\()", replace_bracket, cleaned)

    # Clean punctuation spacing left after removed markers (e.g., "claim [5]." -> "claim.")
    sanitized = re.sub(r"\s+([.,;:!?])", r"\1", sanitized)
    sanitized = re.sub(r"[ \t]+", " ", sanitized)

    # 3. Determine valid cited indices actually present in the sanitized text
    remaining_markers = extract_cited_indices(sanitized)
    valid_cited = [idx for idx in remaining_markers if idx in valid_indices]

    return sanitized.strip(), valid_cited, invalid_indices_found


def clean_section_markdown(
    text: str,
    is_intro: bool = False,
    essay_title: Optional[str] = None,
    known_episode_titles: Optional[List[str]] = None,
) -> str:
    """Normalize a generated essay section.

    - Strips accidental outer ```markdown or ``` code fences.
    - Removes accidental duplicate H1 headings or podcast episode titles used as H1s.
    - Demotes any accidental internal H1 headings (# Heading) to H2 (## Heading).
    - Removes duplicate H2 headings that restate the article title.
    - Strips leaked prompt metadata headers and trailers.
    - Strips draft artifacts and author instructions.
    - Normalizes accidental first-person singular founder anecdotes to objective editorial voice.
    - Preserves legitimate markdown formatting, bullets, bold text, links, and citations.
    """
    if not text:
        return ""

    cleaned = text.strip()

    # 1. Strip accidental outer markdown code fence wrappers
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:markdown|md)?\s*\n?", "", cleaned, flags=re.IGNORECASE).strip()
    if cleaned.endswith("```"):
        cleaned = re.sub(r"\n?\s*```$", "", cleaned).strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:markdown|md)?\s*\n?", "", cleaned, flags=re.IGNORECASE).strip()
    if cleaned.endswith("```"):
        cleaned = re.sub(r"\n?\s*```$", "", cleaned).strip()

    # 2. Process line by line for H1 and H2 heading normalization
    lines = cleaned.split("\n")
    processed_lines = []
    ep_titles_lower = [t.lower().strip() for t in (known_episode_titles or []) if t.strip()]

    for line in lines:
        stripped = line.strip()
        # Check for H1 headings (starts with single '# ', but not '## ')
        if re.match(r"^#\s+[^#]", stripped):
            h1_text = re.sub(r"^#\s+", "", stripped).strip()
            h1_lower = h1_text.lower()

            # Check if this H1 duplicates the essay title
            is_essay_title = is_duplicate_title(h1_text, essay_title)

            # Check if this H1 duplicates a podcast episode title or metadata
            is_episode_title = False
            if (
                h1_lower.startswith("episode:")
                or "guest:" in h1_lower
                or "lenny's podcast" in h1_lower
                or any(ep in h1_lower for ep in ep_titles_lower)
            ):
                is_episode_title = True

            if is_essay_title or is_episode_title:
                # Omit duplicate/metadata H1 line completely
                continue
            else:
                # Accidental section H1 heading -> demote to H2
                if is_duplicate_title(h1_text, essay_title):
                    if is_intro:
                        processed_lines.append("## The Core Tension & Strategic Dilemma")
                else:
                    processed_lines.append(f"## {h1_text}")
        elif re.match(r"^##\s+[^#]", stripped) and essay_title:
            # Check for accidental H2 that duplicates the essay title
            h2_text = re.sub(r"^##\s+", "", stripped).strip()
            if is_duplicate_title(h2_text, essay_title):
                if is_intro:
                    processed_lines.append("## The Core Tension & Strategic Dilemma")
                continue
            processed_lines.append(line)
        else:
            processed_lines.append(line)

    result = "\n".join(processed_lines).strip()

    # 3. Strip leaked retrieval metadata
    result, _ = strip_metadata_leaks(result)

    # 4. Strip draft artifacts and author scaffolding
    result, _ = strip_draft_artifacts(result)

    # 5. Normalize accidental first-person statements
    result = normalize_editorial_voice(result)

    return result


def split_sentences_safely(text: str) -> List[str]:
    """Split text into sentences cleanly, never cutting inside markdown links, citations, or decimals."""
    if not text.strip():
        return []

    sentences: List[str] = []
    current: List[str] = []
    in_bracket = 0  # inside [...]
    in_paren = 0    # inside (...)

    chars = list(text)
    n = len(chars)
    i = 0
    while i < n:
        c = chars[i]
        current.append(c)
        if c == "[":
            in_bracket += 1
        elif c == "]":
            in_bracket = max(0, in_bracket - 1)
        elif c == "(":
            in_paren += 1
        elif c == ")":
            in_paren = max(0, in_paren - 1)
        elif c in (".", "!", "?") and in_bracket == 0 and in_paren == 0:
            # Check not inside decimal number e.g. 1.5
            is_prev_digit = i > 0 and chars[i - 1].isdigit()
            is_next_digit = i + 1 < n and chars[i + 1].isdigit()

            # Check not common abbreviations
            curr_tail = "".join(current[-4:]).lower()
            is_abbrev = curr_tail.endswith(("e.g.", "i.e.", "vs."))

            if not (is_prev_digit and is_next_digit) and not is_abbrev:
                # Next character must be whitespace or end of string
                if i + 1 == n or chars[i + 1].isspace():
                    sent = "".join(current).strip()
                    if sent:
                        sentences.append(sent)
                    current = []
                    # Skip trailing whitespace on same line
                    while i + 1 < n and chars[i + 1] in (" ", "\t"):
                        i += 1
        i += 1

    remainder = "".join(current).strip()
    if remainder:
        sentences.append(remainder)
    return sentences


def trim_section_to_budget(
    section_markdown: str,
    target_words: int = 250,
    max_words: int = 285,
    is_intro: bool = False,
    is_conclusion: bool = False,
) -> str:
    """Trim an overlong section down to its word budget using structure-aware editing.

    Preserves:
    - Section headings (H1/H2).
    - Opening hook & thesis in Section 1 (intro).
    - Final actionable takeaway in Section 5 (conclusion).
    - Grounded citation brackets [1], [2] and Markdown links [text](url).
    - Bullet list structure.
    - Sentence boundaries (never truncates mid-sentence).
    """
    clean_text = section_markdown.strip()
    if not clean_text:
        return ""

    current_words = count_words(clean_text)
    if current_words <= max_words:
        return clean_text

    # 1. Normalize line endings
    clean_text = clean_text.replace("\r\n", "\n").replace("\r", "\n")

    # 2. Extract leading heading if present
    heading_line = ""
    lines = clean_text.split("\n")
    first_non_empty = 0
    while first_non_empty < len(lines) and not lines[first_non_empty].strip():
        first_non_empty += 1

    if first_non_empty < len(lines) and lines[first_non_empty].strip().startswith("#"):
        heading_line = lines[first_non_empty].strip()
        body_text = "\n".join(lines[first_non_empty + 1 :]).strip()
    else:
        body_text = clean_text

    # 3. Split body into structural markdown blocks (paragraphs or lists)
    raw_blocks = [b.strip() for b in re.split(r"\n\s*\n", body_text) if b.strip()]
    if not raw_blocks:
        return heading_line if heading_line else clean_text

    def is_bullet_list(block: str) -> bool:
        block_lines = [l.strip() for l in block.splitlines() if l.strip()]
        return len(block_lines) > 0 and any(re.match(r"^[-*]\s+|\d+[.)]\s+", l) for l in block_lines)

    def is_takeaway_block(block: str) -> bool:
        lower = block.lower()
        return (
            "takeaway" in lower
            or "bottom line" in lower
            or "in summary" in lower
            or lower.startswith(("**the bottom line", "**takeaway", "the bottom line:", "takeaway:"))
        )

    heading_words = count_words(heading_line)
    budget_for_body = max(50, max_words - heading_words)

    # 4. Identify mandatory blocks
    takeaway_block_idx = None
    if is_conclusion and len(raw_blocks) > 1:
        for i in range(len(raw_blocks) - 1, -1, -1):
            if is_takeaway_block(raw_blocks[i]):
                takeaway_block_idx = i
                break
        if takeaway_block_idx is None:
            takeaway_block_idx = len(raw_blocks) - 1

    # 5. Build selected blocks respecting order and priorities
    selected_indices = set()
    if is_intro:
        selected_indices.add(0)

    if takeaway_block_idx is not None:
        selected_indices.add(takeaway_block_idx)

    # Priority ranking for remaining blocks:
    # 0: blocks containing citations [N]
    # 1: bullet list blocks
    # 2: chronological prose blocks
    priority_order = []
    for idx, blk in enumerate(raw_blocks):
        if idx in selected_indices:
            continue
        has_citation = bool(re.search(r"\[\d+\]", blk))
        is_list = is_bullet_list(blk)
        priority_order.append((0 if has_citation else (1 if is_list else 2), idx))

    priority_order.sort(key=lambda x: (x[0], x[1]))

    # Greedily add candidate blocks that fit into budget
    current_selected_words = sum(count_words(raw_blocks[i]) for i in selected_indices)
    for _, idx in priority_order:
        blk_words = count_words(raw_blocks[idx])
        if current_selected_words + blk_words <= budget_for_body:
            selected_indices.add(idx)
            current_selected_words += blk_words

    # If remaining budget exists, add complete sentences from the highest priority unselected prose block
    remaining_budget = budget_for_body - current_selected_words
    if remaining_budget >= 35:
        for _, idx in priority_order:
            if idx not in selected_indices:
                candidate_blk = raw_blocks[idx]
                if not is_bullet_list(candidate_blk):
                    sents = split_sentences_safely(candidate_blk)
                    kept_sents = []
                    s_words = 0
                    for s in sents:
                        sw = count_words(s)
                        if s_words + sw <= remaining_budget:
                            kept_sents.append(s)
                            s_words += sw
                        else:
                            break
                    if kept_sents and s_words >= 25:
                        raw_blocks[idx] = " ".join(kept_sents)
                        selected_indices.add(idx)
                        break

    # Assemble blocks in their original document order to preserve narrative flow
    sorted_indices = sorted(list(selected_indices))
    assembled_blocks = [raw_blocks[i] for i in sorted_indices]
    total_assembled_words = heading_words + sum(count_words(b) for b in assembled_blocks)

    # If still over max_words, trim trailing sentences from the longest non-mandatory block
    if total_assembled_words > max_words:
        excess = total_assembled_words - max_words
        for b_idx in range(len(assembled_blocks)):
            # In conclusion, don't trim the last block if it is the takeaway
            if is_conclusion and b_idx == len(assembled_blocks) - 1:
                continue
            blk = assembled_blocks[b_idx]
            if is_bullet_list(blk):
                continue
            sentences = split_sentences_safely(blk)
            if len(sentences) > 1:
                while len(sentences) > 1 and excess > 0:
                    removed = sentences.pop()
                    excess -= count_words(removed)
                assembled_blocks[b_idx] = " ".join(sentences)
                if excess <= 0:
                    break

    # Re-assemble text
    result_parts = []
    if heading_line:
        result_parts.append(heading_line)
    result_parts.extend(assembled_blocks)
    result = "\n\n".join(result_parts).strip()

    # Safety: Balance markdown bold tags if unbalanced
    if result.count("**") % 2 != 0:
        result += "**"

    return result


def format_essay_sources(
    evidence_entries: List[EvidenceEntry],
    cited_indices: List[int],
) -> str:
    """Format the terminal Markdown Sources section with clickable YouTube timestamp links."""
    unique_indices = []
    for idx in cited_indices:
        if idx not in unique_indices:
            unique_indices.append(idx)

    # Do not attach unreferenced sources if text omitted inline citations
    if not unique_indices:
        return ""

    index_to_entry = {entry.index: entry for entry in evidence_entries}
    lines = ["\n\n---\n\n### Sources"]

    for idx in unique_indices:
        if idx in index_to_entry:
            entry = index_to_entry[idx]
            target_url = entry.source.timestamped_url or entry.source.youtube_url
            guest_str = f" - Guest: {entry.source.guest_name}" if entry.source.guest_name else ""
            ts_str = f" [at {entry.source.timestamp_label}]" if entry.source.timestamp_label else ""

            if target_url:
                lines.append(
                    f"[{entry.index}] [{entry.source.episode_title}{guest_str}{ts_str}]({target_url})"
                )
            else:
                lines.append(
                    f"[{entry.index}] {entry.source.episode_title}{guest_str}{ts_str}"
                )

    return "\n".join(lines)


POPULAR_TECH_ENTITIES = {
    "canva",
    "figma",
    "stripe",
    "airbnb",
    "uber",
    "slack",
    "dropbox",
    "netflix",
    "spotify",
    "zoom",
    "hubspot",
    "salesforce",
}

NUMBER_WORD_MAP = {
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
    "10": "ten",
    "20": "twenty",
    "50": "fifty",
    "100": "hundred",
}

STOP_WORDS = {
    "the", "and", "or", "to", "a", "an", "in", "on", "of", "for", "with", "at",
    "by", "from", "up", "about", "into", "over", "after", "is", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "shall", "should", "may", "might", "must", "can", "could",
    "this", "that", "these", "those", "it", "its", "they", "them", "their",
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
    "all", "any", "both", "each", "few", "more", "most", "other", "some", "such",
    "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "s", "t", "just", "don", "now",
}


def extract_evidence_corpus(evidence_entries: List[EvidenceEntry]) -> str:
    """Concatenate all transcript text from evidence entries into a unified corpus."""
    parts: List[str] = []
    for entry in evidence_entries:
        # EvidenceEntry has: index, source (CitationSource), header, excerpt
        if getattr(entry, "excerpt", None):
            parts.append(entry.excerpt)
        elif getattr(entry, "source", None) and getattr(entry.source, "content", None):
            parts.append(entry.source.content)
    return " ".join(parts)


def verify_essay_grounding(
    text: str,
    evidence_entries: List[EvidenceEntry],
    topic: str = "",
) -> Dict[str, Any]:
    """Audit essay text against retrieved transcript evidence for factual grounding defects.

    Deterministic safeguards inspected:
    1. Direct quotations in quotation marks ("..."): Must match retrieved transcript text.
    2. Numerical metrics & timelines: Numbers, percentages, timelines, quotas must exist in evidence corpus.
    3. Ungrounded company examples: External company names (e.g. Canva, Figma) must be in evidence or topic.
    4. Citation relevance: Citations [N] attached to sentences must have non-zero topical overlap with entry N.

    Returns:
        {
            "is_grounded": bool,
            "unsupported_quotes": List[str],
            "unsupported_metrics": List[str],
            "unsupported_companies": List[str],
            "unrelated_citations": List[str],
            "diagnostics": List[str],
        }
    """
    if not text:
        return {
            "is_grounded": False,
            "unsupported_quotes": [],
            "unsupported_metrics": [],
            "unsupported_companies": [],
            "unrelated_citations": [],
            "diagnostics": ["Essay content is empty"],
        }

    raw_corpus = extract_evidence_corpus(evidence_entries)
    corpus_clean = re.sub(r"\s+", " ", raw_corpus).lower()
    norm_corpus = re.sub(r"[^\w\s]", "", corpus_clean)
    corpus_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", corpus_clean))
    corpus_words = set(corpus_clean.split())

    topic_lower = (topic or "").lower()

    # Isolate body text before terminal Sources section
    body_text = text.split("## Sources")[0] if "## Sources" in text else text

    # Helper: Check if number exists in evidence or topic
    def is_number_in_evidence(num_str: str) -> bool:
        clean_num = num_str.replace(",", "")
        if clean_num in corpus_numbers:
            return True
        if clean_num in NUMBER_WORD_MAP and NUMBER_WORD_MAP[clean_num] in corpus_words:
            return True
        if clean_num in topic_lower or (clean_num in NUMBER_WORD_MAP and NUMBER_WORD_MAP[clean_num] in topic_lower):
            return True
        return False

    # 1. Direct quotations verification
    unsupported_quotes: List[str] = []
    quote_candidates = re.findall(r'["“]([^"”\n]+)["”]', body_text)
    for raw_q in quote_candidates:
        q = raw_q.strip()
        words = q.split()
        if len(words) < 3 or len(q) < 15:
            continue
        norm_q = re.sub(r"[^\w\s]", "", q).lower()
        if norm_q in norm_corpus:
            continue
        # Check 4-word window overlap
        norm_words = norm_q.split()
        found_subsequence = False
        if len(norm_words) >= 4:
            for i in range(len(norm_words) - 3):
                window = " ".join(norm_words[i : i + 4])
                if window in norm_corpus:
                    found_subsequence = True
                    break
        if not found_subsequence:
            unsupported_quotes.append(q)

    # 2. Numerical metrics & timelines verification
    unsupported_metrics: List[str] = []

    # 2a. Timelines: \b(\d+)\s*(days?|weeks?|months?|years?|hours?)\b
    timeline_matches = re.finditer(r"\b(\d+)\s*(days?|weeks?|months?|years?|hours?)\b", body_text, re.IGNORECASE)
    for m in timeline_matches:
        num, unit = m.group(1), m.group(2).lower()
        full_match = m.group(0)
        # Ship 30 structural framework exemption: 30 days / 30-day
        if num == "30" and "day" in unit:
            continue
        if not is_number_in_evidence(num):
            unsupported_metrics.append(f"{full_match} (timeline not in evidence)")

    # 2b. Percentage allocations: \b(\d+(?:\.\d+)?)\s*%(?!\w)
    pct_matches = re.finditer(r"\b(\d+(?:\.\d+)?)\s*%(?!\w)", body_text)
    for m in pct_matches:
        num = m.group(1)
        full_match = m.group(0)
        if not is_number_in_evidence(num):
            unsupported_metrics.append(f"{full_match} (percentage not in evidence)")

    # 2c. Customer/account/rep quotas: \b(\d+)\s*(?:paying\s+)?(customers?|clients?|accounts?|users?|reps?|hires?|engineers?|salespeople)\b
    quota_matches = re.finditer(
        r"\b(\d+)\s*(?:paying\s+)?(customers?|clients?|accounts?|users?|reps?|hires?|engineers?|salespeople)\b",
        body_text,
        re.IGNORECASE,
    )
    for m in quota_matches:
        num = m.group(1)
        full_match = m.group(0)
        if not is_number_in_evidence(num):
            unsupported_metrics.append(f"{full_match} (quota not in evidence)")

    # 2d. Currency amounts: \$(\d+(?:[.,]\d+)?(?:\s*(?:k|m|b|million|billion|thousand))?)\b
    curr_matches = re.finditer(
        r"\$(\d+(?:[.,]\d+)?(?:\s*(?:k|m|b|million|billion|thousand))?)\b",
        body_text,
        re.IGNORECASE,
    )
    for m in curr_matches:
        full_match = m.group(0)
        num_part = re.search(r"\d+", full_match)
        if num_part and not is_number_in_evidence(num_part.group(0)):
            unsupported_metrics.append(f"{full_match} (currency metric not in evidence)")

    # 3. Ungrounded Company Case Studies
    unsupported_companies: List[str] = []
    lower_body = body_text.lower()
    for comp in POPULAR_TECH_ENTITIES:
        if re.search(rf"\b{re.escape(comp)}\b", lower_body):
            if comp not in corpus_clean and comp not in topic_lower:
                unsupported_companies.append(comp.capitalize())

    # 4. Citation Relevance / Topical Overlap Check
    unrelated_citations: List[str] = []
    index_to_entry = {entry.index: entry for entry in evidence_entries}
    sentences = re.split(r"(?<=[.!?])\s+", body_text)
    for sent in sentences:
        cited_in_sent = [int(m) for m in re.findall(r"\[(\d+)\]", sent)]
        for c_idx in cited_in_sent:
            if c_idx in index_to_entry:
                entry = index_to_entry[c_idx]
                # Use actual EvidenceEntry fields: excerpt, header, source.guest_name, source.episode_title, source.content
                entry_source = getattr(entry, "source", None)
                source_content = getattr(entry_source, "content", "") if entry_source else ""
                source_title = getattr(entry_source, "episode_title", "") if entry_source else ""
                source_guest = getattr(entry_source, "guest_name", "") if entry_source else ""
                entry_text_clean = (
                    f"{getattr(entry, 'excerpt', '')} {getattr(entry, 'header', '')} "
                    f"{source_guest} {source_title} {source_content}"
                ).lower()
                # Extract content words from sentence
                sent_clean = re.sub(r"[^\w\s]", " ", sent.lower())
                sent_words = [w for w in sent_clean.split() if len(w) >= 4 and w not in STOP_WORDS]
                if len(sent_words) >= 4:
                    overlap_found = any(w in entry_text_clean for w in sent_words)
                    if not overlap_found:
                        unrelated_citations.append(
                            f"Citation [{c_idx}] attached to assertion with no source topic overlap: '{sent[:50].strip()}...'"
                        )

    diagnostics: List[str] = []
    if unsupported_quotes:
        diagnostics.append(f"{len(unsupported_quotes)} unverified quotation(s)")
    if unsupported_metrics:
        diagnostics.append(f"{len(unsupported_metrics)} unsupported numerical metric(s)")
    if unsupported_companies:
        diagnostics.append(f"{len(unsupported_companies)} ungrounded company example(s)")
    if unrelated_citations:
        diagnostics.append(f"{len(unrelated_citations)} ungrounded citation attachment(s)")

    is_grounded = (
        len(unsupported_quotes) == 0
        and len(unsupported_metrics) == 0
        and len(unsupported_companies) == 0
        and len(unrelated_citations) == 0
    )

    return {
        "is_grounded": is_grounded,
        "unsupported_quotes": unsupported_quotes,
        "unsupported_metrics": unsupported_metrics,
        "unsupported_companies": unsupported_companies,
        "unrelated_citations": unrelated_citations,
        "diagnostics": diagnostics,
    }
