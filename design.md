# Design Specification & UI/UX Guidelines
## The Lenny Growth Assistant

**Document Status**: Baseline / Phase 1 — Step 1 Architecture Draft  
**Target Completion Date**: 12 October 2026, End of Day  
**Author**: Forward Deployed Engineering & AI Solutions Architecture Team  

---

## 1. UI/UX Principles
The Lenny Growth Assistant interface is designed around four core tenets:

1. **Information Density with Scannability**: Product managers and startup operators value dense, high-signal insights over fluffy conversational filler. The UI uses disciplined typography, collapsible citation cards, and distinct visual hierarchies.
2. **Side-by-Side Dual Workspace**: Synthesizing transcripts into actionable essays and artifacts requires concurrent visibility. The interface prioritizes a side-by-side split screen where conversational grounding happens on the left and generated artifacts render on the right.
3. **Transparency of Grounding**: Users must never question whether a claim is genuine or hallucinated. Citations are first-class visual components displaying the podcast episode title, guest name, timestamp, and verbatim excerpt.
4. **Lightweight & High Performance**: Running on an 8 GB RAM laptop requires minimal browser overhead. The frontend employs vanilla CSS with modern CSS variables, zero heavy component bloat, and instantaneous rendering.

---

## 2. Information Architecture
The application is structured into three primary structural pillars:

```
+---------------------------------------------------------------------------------------+
|  HEADER: App Title | Model Indicator (Ollama qwen2.5:1.5b) | Provider / Status Badges |
+------------------------------------+----------------------------------+---------------+
|  SESSION SIDEBAR                   |  CHAT WORKSPACE                  | ARTIFACT      |
|  - New Session Button              |  - Message Stream                | VIEWER        |
|  - Recent Sessions List            |  - Grounded Citation Drawer      | - Tab Header  |
|  - Ingestion Stats                 |  - Action Buttons (Write Essay)  | - MD Preview  |
|                                    |  - Input Field & Prompt Controls | - HTML Iframe |
+------------------------------------+----------------------------------+---------------+
```

---

## 3. Application Layout & Workspace Layout
The layout uses a 3-column CSS Grid / Flexbox architecture:

1. **Left Column — Session Management Sidebar (280px)**:
   - Header with `+ New Chat Session` CTA.
   - Chronological list of past conversational sessions.
   - Quick metadata (timestamp, conversation turn count, topic summary).
   - Collapsible on tablet / mobile screens via a toggle button.

2. **Center Column — Conversational Chat Workspace (Flexible / 1fr)**:
   - Pinned conversation messages.
   - Visual distinction between User queries (accent-tinted cards) and Assistant responses (clean slate cards).
   - Interactive Citation accordion attached to every grounding claim.
   - Floating or docked prompt input bar with quick prompt templates ("Summarize Elena Verna on PLG", "Compare B2B Pricing").

3. **Right Column — Sandboxed Artifact Viewer (380px – 500px, resizable/collapsible)**:
   - Dedicated space for rendered outputs (Ship 30 for 30 essays, HTML cards, frameworks).
   - Header controls: `Raw Markdown`, `Rendered Preview`, `Copy to Clipboard`, and `Download`.
   - Collapses automatically when no artifact is active; expands smoothly upon artifact generation.

---

## 4. Chat Interactions & Conversational Flows

### 4.1 New Session Flow
1. User clicks `+ New Chat Session`.
2. Frontend dispatches `POST /api/sessions` to the backend.
3. Backend generates a UUID `session_id` in PostgreSQL and returns an initial state payload.
4. Chat workspace clears previous messages and presents a welcoming hero card with prompt starters.
5. URL updates or session state mounts the active `session_id`.

### 4.2 Standard Grounded Inquiry Flow
1. User types a query: *"What are the primary metrics Gustaf Alströmer recommends for tracking retention?"*
2. Input field locks, showing an active loading pulse (`Searching transcript vector store...`).
3. Assistant streams response chunks or renders the synthesized response.
4. Attached below the message is a **Citations Drawer**:
   - Badge: `3 Sources Cited`.
   - Click to expand: Cards showing *Episode 42: Gustaf Alströmer on Growth Loops*, timestamp, and relevant quote excerpt.

### 4.3 Model & Provider Selection Flow
- The header displays an interactive status badge indicating the active provider (e.g., `Ollama: qwen2.5:1.5b (Local)`).
- Hovering shows backend latency and connection health.
- Clicking the badge opens a lightweight configuration modal displaying active provider settings, with options to switch between local Ollama and Cloud LLM (OpenAI/Anthropic) when configured in `.env`.

---

## 5. Specialized Interactions

### 5.1 Ship 30 for 30 Essay Generation
- Triggered either through direct conversational request (*"Write a Ship 30 for 30 essay about..."*) or by clicking the `Generate Essay` shortcut button on a chat response.
- The assistant invokes the `ship30_essay_writer` tool.
- UI displays a specialized progress tracker:
  1. *Retrieving core transcript frameworks...*
  2. *Structuring 1,250-word outline (Hook, Core Pillars, Takeaways)...*
  3. *Polishing formatting (2-sentence paragraphs, bullet points, selective bolding)...*
- Upon completion, the Artifact Viewer slides open with the rendered essay.

### 5.2 Artifact Viewer & Untrusted HTML Sandboxing
- Generated artifacts can be Markdown or HTML/CSS.
- **Untrusted Content Principle**: All model-generated HTML is treated as strictly untrusted and potentially malicious.
- **Sandboxed Iframe Architecture**:
  - Rendered inside an isolated `<iframe sandbox srcdoc="...">` element.
  - **JavaScript Disabled by Default**: The `sandbox` attribute strictly omits `allow-scripts` and `allow-same-origin`, preventing script execution, cookie access, local storage access, or DOM interaction with the parent application.
  - Prevents top-level navigation, popups, and modal dialogs (no `allow-top-navigation`, `allow-popups`, or `allow-modals`).
- **HTML Sanitization Pipeline**:
  - Model output passes through a strict HTML sanitizer before reaching the viewer DOM.
  - Strips all `<script>`, `<object>`, `<embed>`, `<link>`, `<iframe>`, and `<form>` tags, as well as inline `on*` event handlers (e.g., `onload`, `onerror`, `onclick`) and `javascript:` URIs.
  - Permits only semantic HTML tags and styling required for displaying structured assessment frameworks (e.g., headings, paragraphs, lists, tables, spans, blockquotes, code blocks).
- **Restrictive Content Security Policy (CSP)**:
  - Embeds a restrictive `<meta http-equiv="Content-Security-Policy">` within the iframe's `srcdoc`:
    `default-src 'none'; style-src 'unsafe-inline'; img-src data: https:; script-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'none';`
  - Blocks all external script loading, network exfiltration, resource injection, and unwanted page redirection.

---

## 6. System State Management

### 6.1 Empty States
- **New Session**: Displays clear value propositions and four clickable starter cards ("PLG vs Sales-Led", "Retention Benchmarks", "Pricing Experiments", "Hiring First PM").
- **Empty Artifact Viewer**: Displays a subtle icon, placeholder description, and explanation that artifacts generated during chat will appear here.

### 6.2 Loading States
- Micro-skeleton animations for message bubbles during RAG search.
- Streaming token animation with an accent cursor.
- Disabled input buttons during active generation to prevent race conditions.

### 6.3 Error States
- **Ollama Offline**: Distinct banner: *"Ollama local daemon is unreachable at http://localhost:11434. Please start Ollama or verify your model."*
- **Insufficient Evidence**: Honest fallback card: *"No podcast transcripts directly cover this topic with high confidence. The assistant refrains from fabricating advice."*
- **Network / Database Disconnect**: Non-blocking toast notification with a `Retry` action.

---

## 7. Responsive Layout & Breakpoints
- **Desktop (≥ 1280px)**: 3-column layout (Sidebar + Chat + Artifact Viewer).
- **Laptop / Tablet Landscape (1024px – 1279px)**: Sidebar collapsible via hamburger button; Artifact Viewer docked or toggled via tab.
- **Mobile (< 768px)**: Single column view with bottom navigation bar to switch between Chat, History, and Artifact tabs.

---

## 8. Accessibility Considerations (a11y)
- **Keyboard Navigation**: Full tab index traversal across session buttons, input forms, and citation cards.
- **Color Contrast**: Compliant with WCAG 2.1 AA standards (minimum 4.5:1 contrast ratio between text `#f8fafc` and background `#0f172a`).
- **Screen Reader Announcements**: `aria-live="polite"` regions on chat stream containers so screen readers announce incoming assistant answers.
- **Semantic HTML**: Proper `<header>`, `<main>`, `<aside>`, `<nav>`, and heading hierarchies (`h1` -> `h2` -> `h3`).

---

## 9. Design Decisions and Rationale
1. **Dark Slate Theme (`#0f172a` palette)**: Provides high readability, reduces eye fatigue during long reading/synthesis sessions, and aligns with modern developer tool aesthetic standards.
2. **Vanilla CSS Tokens over Heavy UI Kits**: Avoids loading 100+ MB of `node_modules` for Tailwind or MUI, crucial for ensuring responsiveness on an 8 GB RAM laptop.
3. **Tabbed Artifact Viewer**: Treating artifacts as distinct entities rather than burying them inside conversational bubbles matches standard professional IDE / copilot workflows.
