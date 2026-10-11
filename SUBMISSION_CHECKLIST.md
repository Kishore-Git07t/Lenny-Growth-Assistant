# Final Submission Readiness Checklist
## The Lenny Growth Assistant — Oogway Labs Assessment

**Assignment Deadline**: October 12, 2026, End of Day  
**Evaluation Target**: Oogway Labs Forward Deployed Engineer Assignment  

Use this checklist to track and verify each submission deliverable before submitting.

---

## 1. Technical Implementation & Automated Verification

- [ ] **Backend Automated Regression Test Suite**
  - Run: `pytest backend/tests/ -v`
  - Target: Verify all tests pass (incorporating Phase 7 cloud models and Phase 8 container configurations).
- [ ] **Frontend Production Bundle Build**
  - Run: `cd frontend && npm run build`
  - Target: Bundle compiles cleanly to `frontend/dist` without JSX/CSS compilation errors.
- [ ] **Application Smoke Test (Local Dev)**
  - Backend starts on `http://localhost:8000`.
  - Frontend starts on `http://localhost:5173`.
  - Database connects and `/api/ready` returns `{"status":"ready","database":"connected"}`.
- [ ] **Local Inference Verification (Ollama)**
  - Local Ollama service is active at `http://localhost:11434`.
  - `qwen2.5:1.5b` and `nomic-embed-text` are present.
  - Conversational turn completes with verified citations drawer.
- [ ] **Cloud Inference Verification (Google Gemini - If Configured)**
  - `GEMINI_API_KEY` configured in `.env` (free tier via Google AI Studio).
  - Model selector modal switches to Google Gemini `gemini-2.5-flash`.
  - Fast cloud turn completes successfully.
- [ ] **Ship 30 for 30 Essay Verification**
  - Essay generates with structured outline and ~1,250 words target.
  - Essay renders cleanly in the right-hand panel.
- [ ] **HTML/CSS Sandboxed Artifact Verification**
  - Design artifact generates and sanitizes without errors.
  - Preview renders in sandboxed iframe (`sandbox=""` with strict CSP).
  - HTML and CSS tabs display syntax-highlighted code with copy buttons.
- [ ] **PostgreSQL Persistence Verification**
  - Refresh browser; verify that sessions, messages, essays, and HTML artifacts reload intact.
- [ ] **Docker Compose Stack Verification**
  - Run: `docker compose up --build -d`
  - Verify all 3 containers are healthy (`docker compose ps`).
  - Access application at `http://localhost:8080`.
  - Confirm isolated named volume (`lenny_compose_postgres_data`) does not affect development data.

---

## 2. Evidence, Video & Documentation

- [ ] **Authentic Coding Agent Evidence Capture**
  - Collect real JSONL execution logs from Pi Coding Agent per `agent_transcripts/EVIDENCE_COLLECTION_GUIDE.md`.
  - Sanitize all API keys and local paths.
  - Place sanitized evidence in `agent_transcripts/`.
- [ ] **Demonstration Video (2–3 Minutes)**
  - Record camera-on walkthrough following `DEMO_RECORDING_GUIDE.md`.
  - Demonstrate: Introduction, React UI, Grounded Q&A with Citations, Model Switching, Ship 30 Essay, HTML/CSS Sandboxed Preview, Persistence, and Architecture.
  - Upload to YouTube / Loom as Unlisted or Public.
  - Verify audio/video clarity and ensure duration does not exceed 3 minutes.
- [ ] **Documentation Review**
  - `README.md`: Verified, comprehensive runbook and architectural diagrams.
  - `PRD.md`: Verified requirements matrix and acceptance criteria.
  - `architecture.md`: Verified system diagrams and security boundaries.
  - `design.md`: Verified UI/UX principles and tokens.

---

## 3. Security, Repository Hygiene & Submission

- [ ] **Git & Secrets Security Audit**
  - Confirm `.env` is NOT tracked by Git (`git status --ignored`).
  - Confirm no real API keys exist in committed code.
  - Confirm internal notes (`.local/`, `.pi/`) are excluded.
  - Confirm raw large datasets and virtual environments are ignored.
- [ ] **Public GitHub Repository Setup**
  - Create public GitHub repository: `https://github.com/<your-username>/Lenny-Growth-Assistant`.
  - Push the sanitized codebase:
    ```bash
    git add .
    git commit -m "feat: complete Lenny Growth Assistant for Oogway Labs assessment"
    git push origin main
    ```
- [ ] **Final Submission Form**
  - Public GitHub repository URL.
  - Demonstration video URL (YouTube / Loom).
  - Candidate contact information.
  - Submit before deadline: **October 12, 2026, End of Day**.
