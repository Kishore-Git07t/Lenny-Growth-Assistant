---
name: ship30_essay
version: 1.0.0
description: Transform grounded Lenny's Podcast transcript evidence into a 1,250-word structured digital essay adhering to official Ship 30 for 30 digital writing principles.
author: Oogway Labs
tags:
  - content-generation
  - ship30
  - digital-writing
  - grounded-rag
  - essay
---

# Ship 30 for 30 Essay Skill: Writing Guide & Generation Specification

## 1. Purpose and Activation
This skill transforms verified transcript passages from Lenny's Podcast into a professionally structured, highly skimmable digital essay of approximately 1,250 words (practical acceptance range: 1,100–1,400 words).

It is activated when a user requests an essay based on conversation topics (e.g., via `POST /api/sessions/{session_id}/essay`), transforming raw conversational transcripts into actionable, high-signal digital writing.

## 2. Core Ship 30 for 30 Digital Writing Principles
The skill encodes the proven principles of digital writing established by Ship 30 for 30:

1. **Clear Over Clever Headlines**: The title must immediately tell the target reader who the piece is for and what tangible benefit they will receive. Never use vague puns, cryptic metaphors, or inside jokes.
2. **The 1-3-1 & Compelling Hook**: Open with an immediate tension, high-stakes question, or counter-intuitive reality. Never start with throat-clearing fluff (e.g. "In today's fast-paced world").
3. **Single Coherent Direction**: The essay must pursue exactly one central thesis from start to finish. Every section must directly serve this core insight.
4. **Structured Modular Rhythm**: Use consistent, predictable formatting. Every section begins with a clear H2 heading that communicates a concrete idea, not a generic topic label.
5. **Visual Pacing & Anti-Wall-of-Text Formatting**:
   - Vary paragraph length: alternate between 1-sentence punchy declarations, 2-3 sentence explanatory context, and structured lists.
   - Break parallel ideas, symptoms, mistakes, or execution steps into readable bulleted lists.
   - Use selective **bold emphasis** on the most important takeaway phrase in key paragraphs.
6. **High-Signal Practicality Over Platitudes**: Deliver specific decision criteria, strategic milestones, and operational mechanics rather than vague motivational slogans. When the evidence provides concrete figures (e.g. customer milestones from guest experience), preserve them accurately; never fabricate artificial metrics (e.g. '100 days', '20% of time') when the evidence is qualitative.
7. **Decisive Actionable Takeaway**: Conclude with a specific, immediate implementation framework or decision rule the reader can apply today.
8. **Objective Editorial Voice**: Write with an authoritative, objective third-person perspective. Never write in the first-person singular ("I", "my", "as a founder I often wonder"). Never invent personal founder anecdotes or pretend to be the podcast guest.

## 3. Strict Grounding and Evidence Safeguards
1. **Verbatim Fidelity**: All factual assertions, operational frameworks, and concrete recommendations must originate from verified podcast transcript passages provided in the evidence context.
2. **No Hallucination**: Do not fabricate case studies, statistics, metrics, or quotations. Never invent guest credentials, titles, or company histories.
3. **Speaker Attribution Integrity**: Distinguish the episode guest from host Lenny Rachitsky or other participants. Do not attribute a quote or opinion to a guest unless the transcript evidence explicitly identifies them as the speaker.
4. **Citation Discipline & Reconciliation**:
   - Reference transcript evidence using numeric citation tags (e.g., `[1]`, `[2]`).
   - Every inline citation marker must correspond to a real retrieved transcript source.
   - Every cited marker must have a matching entry in the terminal Sources section.
   - Never invent episode titles, guests, timestamps, video IDs or transcript passages.
   - Never fabricate source entries to repair unsupported citation markers.
   - Unsupported or orphaned markers (e.g., `[5]` when only `[1]`–`[4]` exist) are stripped and trigger honest `partial` status.
5. **No Leaked Metadata or Draft Artifacts**:
   - Never copy retrieval prompt headers (e.g., `[1] (Episode: ...)` or `- Evidence: [5] (...)`) into essay text.
   - Never include author instructions, scaffolding, or placeholders (e.g., `"Please replace them with..."`, `"[insert evidence here]"`).
6. **No Duplicate Article Titles or Code Fences**:
   - The essay must have exactly one H1 headline at the top.
   - The article headline must never be repeated as an H2 section heading.
   - Never wrap section text in ```markdown code fences.
7. **Numerical Grounding**: Any specific customer counts, percentages, dollar figures, or timelines MUST come directly from retrieved transcript evidence. Qualitative guest advice (e.g., "close early customers yourself") must never be converted into unsupported quantitative claims (e.g., "10 customers in 100 days").
8. **Quotation Fidelity**: Text enclosed in quotation marks ("...") must match retrieved transcript statements near-verbatim. Paraphrasing must be integrated in third-person editorial prose without quotation marks.
9. **Company Example Integrity**: Prohibit injecting popular ungrounded tech companies (e.g., Canva, Figma, Stripe, Airbnb) unless explicitly cited and discussed in the retrieved transcript passages.
10. **Citation-Assertion Topical Relevance**: Inline citation markers ([N]) must directly substantiate the adjacent factual assertion; decorative citations attached to unrelated assertions are strictly prohibited.
11. **Deterministic Grounding Audit & Honest Status**:
    - Status is marked `completed` ONLY when the essay satisfies the 1,100–1,400 word requirement, valid structure, zero duplicate titles, zero draft instructions, zero code fences, complete citation reconciliation, and passes the deterministic grounding audit.
    - If evidence is insufficient, unsupported citations exist, or grounding defects are detected, return honest `partial` status with an advisory disclaimer.

## 4. Multi-Stage Structural Blueprint (~1,250 Words)

To run reliably on resource-constrained local models (such as `qwen2.5:1.5b` on an 8 GB RAM laptop), the essay is orchestrated in five discrete, sequential sections:

### Section 1: Headline, Hook & Central Thesis (~230 words, max 260 words)
- **H1 Headline**: Clear, benefit-driven title tailored to the target reader (6–10 words; no formulaic prefixes).
- **H2 Heading**: Distinct operational heading (e.g. `## The Core Tension & Strategic Dilemma`; never duplicate the H1 title).
- **Hook**: 1-3-1 structure presenting the core dilemma or counter-intuitive reality.
- **The Core Problem**: Why conventional wisdom fails founders or operators.
- **The Central Thesis**: The foundational insight revealed by Lenny's Podcast guests.

### Section 2: Foundational Principles & Thresholds (~260 words, max 285 words)
- **H2 Heading**: An assertive claim stating the first principle.
- **The Core Metric / Threshold**: Concrete trigger points (e.g., customer count, time allocation).
- **Verbatim Grounded Evidence**: What the guest observed from direct company experience.
- **The Rationalization**: Why this threshold is non-negotiable.

### Section 3: The Operational Playbook & Tactics (~260 words, max 285 words)
- **H2 Heading**: The step-by-step tactical execution framework.
- **Skimmable Bullet List**: 3–5 concrete actions or criteria.
- **Real-World Mechanics**: How the strategy is executed in practice.
- **Contrast**: What high-performers do differently from struggling teams.

### Section 4: Common Pitfalls & Counter-Intuitive Traps (~260 words, max 285 words)
- **H2 Heading**: The dangerous failure mode or expensive mistake.
- **The Seductive Shortcut**: Why founders fall into this trap.
- **Transcript Grounding**: Evidence-backed examples of what breaks when done prematurely or incorrectly.
- **The Correction**: The disciplined operational antidote.

### Section 5: The Actionable Framework & Closing Takeaway (~240 words, max 270 words)
- **H2 Heading**: The 30-day implementation rule or executive checklist.
- **Action Checklist**: Clear, actionable bulleted summary for the reader.
- **The Bottom Line**: A memorable, 1-sentence closing synthesis that sticks.
- **Sources**: Clean, timestamped YouTube references strictly matching verified inline citations.

## 5. Quality Checklist & Acceptance Criteria
- [ ] Word Count within 1,100–1,400 words (nominal target: 1,250 words).
- [ ] Exactly one H1 headline; zero duplicate H2 headings matching the title.
- [ ] Target reader clearly stated or addressed in headline and hook.
- [ ] At least 3 H2 section headings containing complete, informative ideas.
- [ ] At least 2 bulleted or numbered lists for skimmability.
- [ ] Selective bolding on key insight phrases.
- [ ] All empirical claims cited using `[N]` notation matching verified evidence entries.
- [ ] Zero leaked prompt metadata lines or inline headers (`(Episode: ...)`, `Evidence: [N]`).
- [ ] Zero drafting scaffolding, placeholders, or author instructions (`Please replace...`).
- [ ] Zero fabricated citations or sources (e.g. no phantom `[5]` matching unindexed podcasts).
- [ ] Verified YouTube timestamps included in the terminal Sources block.
- [ ] Honest completion status: `completed` only when all validation checks pass.
