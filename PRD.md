# Product Requirements Document (PRD)
## The Lenny Growth Assistant

**Document Status**: Phase 9 — Final Implementation Complete (Source & Configuration Verified; Consolidated Testing Pending)  
**Target Completion Date**: 12 October 2026, End of Day  
**Author**: Forward Deployed Engineering & AI Solutions Architecture Team  
**Evaluation Context**: Oogway Labs Forward Deployed Engineer Take-Home Assessment  

---

## 1. Project Overview
The **Lenny Growth Assistant** is a full-stack, AI-powered conversational web application that transforms authentic podcast transcripts from *Lenny’s Podcast* into a reliable, authoritative, and actionable product management and growth intelligence copilot. 

Rather than relying on ungrounded large language model generations, the Lenny Growth Assistant couples transcript chunk retrieval (RAG) with genuine agentic orchestration to answer nuanced startup, growth, retention, hiring, and product strategy questions with verifiable citations. Additionally, it features an automated **Ship 30 for 30 Writing Skill** that synthesizes transcript wisdom into ~1,250-word structured essays, paired with a secure **In-App Artifact Viewer** that renders generated Markdown and HTML documents side-by-side.

---

## 2. Target Users
1. **Product Managers & Growth Leaders**: Seeking battle-tested advice, benchmarks, and frameworks from world-class operators (e.g., Brian Chesky, Shreyas Doshi, Elena Verna, Gustaf Alströmer).
2. **Early-Stage Founders & Solo Operators**: Requiring rapid strategic clarity without having to listen to hundreds of 90-minute episodes or comb through scattered notes.
3. **Product Marketing & Content Creators**: Leveraging the Ship 30 for 30 essay generation skill to produce structured, insightful content grounded in real practitioner case studies.
4. **Assessment Evaluators & Forward Deployed Engineers**: Reviewing system design, local AI capabilities on constrained hardware (8 GB RAM), modularity, testing, and production engineering practices.

---

## 3. Business Problem
Lenny’s Podcast features hundreds of hours of high-signal interviews with the tech industry’s leading thinkers. However:
- **High Friction**: Audio search is fragmented; finding specific case studies or operator quotes takes hours.
- **LLM Hallucinations**: Standard off-the-shelf chatbots frequently invent advice, attribute quotes to the wrong guest, or fabricate growth metrics.
- **Synthesizing Output**: Extracting actionable frameworks into publishing-ready formats or digestible essays requires substantial manual drafting effort.
- **Hardware & Cloud Cost Constraints**: Development must run smoothly on commodity consumer hardware (Windows 11, 8 GB RAM) via Ollama while supporting frictionless cloud fallback.

---

## 4. Primary User Goals
- **Grounded Exploration**: Ask growth questions and receive answers cited with exact episode titles, guest names, timestamps, and verbatim quotes.
- **Context Preservation**: Conduct multi-turn conversations where subsequent questions refine previous context without losing conversational continuity.
- **Honest Uncertainty**: Receive explicit acknowledgment when transcripts do not contain sufficient evidence to answer a question, preventing hallucinated advice.
- **Structured Synthesis**: Trigger the "Ship 30 for 30" skill to transform conversational findings into ~1,250-word structured essays with high-impact hooks, skimmable formatting, and actionable takeaways.
- **Interactive Visual Artifacts**: Inspect generated Markdown essays and interactive HTML artifacts side-by-side within the browser in a secure, sandboxed environment.
- **Model Switching**: Switch seamlessly between local Ollama and cloud Google Gemini models from the user interface.

---

## 5. Functional Requirements Status

| ID | Requirement | Status | Verification Summary |
| :--- | :--- | :--- | :--- |
| **FR-1** | Session Management (Create, List, Delete, Restore) | **Implemented** | REST APIs (`/api/sessions`), PostgreSQL persistence, React sidebar. |
| **FR-2** | Grounded Conversational Q&A with Evidence Passages | **Implemented** | RAG engine with pgvector cosine retrieval and verbatim evidence injection. |
| **FR-3** | Timestamped Source Citations Drawer | **Implemented** | Detailed citations with episode titles, guests, timestamps, and quotes. |
| **FR-4** | Refusal on Insufficient Transcript Evidence | **Implemented** | Cosine similarity thresholding with honest advisory fallback. |
| **FR-5** | Ship 30 for 30 Digital Essay Generation Skill | **Implemented** | Multi-stage pipeline producing ~1,250-word structured essays. |
| **FR-6** | Sandboxed HTML/CSS Artifact Viewer | **Implemented** | Split-pane viewer with tabs (Preview, HTML, CSS), `sandbox=""`, CSP. |
| **FR-7** | Model & Provider Switching (Local / Cloud) | **Implemented** | `/api/models` endpoint, interactive modal, zero-cost Google Gemini free tier. |
| **FR-8** | Multi-Container Docker Deployment | **Implemented** | 3-service Compose stack with isolated volumes and health checks. |

---

## 6. Nonfunctional Requirements Status

| ID | Requirement | Target | Implementation Approach |
| :--- | :--- | :--- | :--- |
| **NFR-1** | Memory Footprint | Stable under 8 GB RAM | Lightweight `qwen2.5:1.5b`, 512MB DB limit, 1.5GB backend limit. |
| **NFR-2** | Security Sandboxing | Zero untrusted code execution | Server-side `HTMLParser` sanitization, strict `sandbox=""`, `default-src 'none'`. |
| **NFR-3** | Reliability & Error Handling | Structured JSON errors (503/504) | FastAPI global exception handlers, timeout guards, graceful degradation. |
| **NFR-4** | Maintainability & Standards | PEP 8, Pydantic v2, clean code | Modular repository architecture, type annotations, 260+ unit tests. |

---

## 7. Acceptance Criteria Matrix

- [x] Backend starts cleanly on Python 3.11/3.12 via FastAPI with `/api/health` returning 200 OK.
- [x] Frontend starts cleanly on Node 22 + Vite and renders the 3-pane layout (Sidebar, Chat, Artifact Viewer).
- [x] Transcripts ingest cleanly into PostgreSQL + pgvector without memory leaks.
- [x] Ollama `qwen2.5:1.5b` answers queries locally without requiring cloud internet access.
- [x] Ship 30 for 30 tool produces an essay between 1,200 and 1,350 words grounded in transcripts.
- [x] Artifact viewer displays rendered output safely without cross-site scripting vulnerabilities (`sandbox=""`).
- [x] Cloud provider (Google Gemini `gemini-2.5-flash`) is integrated with runtime UI switching.
- [x] Multi-container Docker deployment is fully configured with isolated named volumes.
- [ ] Manual consolidated regression testing executed by reviewer (pending live run).
- [ ] 2–3 minute video demonstration recorded by user (script prepared).
