# The Lenny Growth Assistant
> An AI-powered conversational knowledge copilot transforming *Lenny’s Podcast* transcripts into reliable, grounded growth frameworks, Ship 30 for 30 digital essays, and sandboxed HTML/CSS design artifacts.

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/Frontend-React%2018%20%2B%20Vite-61DAFB.svg)](https://reactjs.org/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL%2017%20%2B%20pgvector-336791.svg)](https://www.postgresql.org/)
[![Pi Agent](https://img.shields.io/badge/Agent-Pi%20Coding%20Agent%20RPC-orange.svg)](https://github.com/earendil-works/pi)
[![Ollama](https://img.shields.io/badge/Local%20LLM-Ollama%20qwen2.5%3A1.5b-black.svg)](https://ollama.ai/)
[![Google Gemini](https://img.shields.io/badge/Cloud%20LLM-Google%20Gemini%202.5%20Flash-4285F4.svg)](https://aistudio.google.com/)
[![Docker](https://img.shields.io/badge/Container-Docker%20Compose-2496ED.svg)](https://www.docker.com/)

---

## 1. Project Introduction

**The Lenny Growth Assistant** is an agentic, full-stack knowledge retrieval and synthesis copilot built for the Oogway Labs Forward Deployed Engineer technical assessment. It grounds open-ended conversational inquiry in hundreds of hours of wisdom from [Lenny’s Podcast](https://github.com/ChatPRD/lennys-podcast-transcripts), delivering practitioner-verified frameworks, high-impact digital essays, and live-rendered web design artifacts.

### The Problem Solved
1. **Unverifiable Chatbot Hallucinations**: Standard LLMs invent growth metrics, mix up case studies, and attribute quotes to the wrong startup operators.
2. **Audio Knowledge Fragmentation**: Hundreds of 90-minute episodes contain gold-standard product wisdom, but searching across them manually is impractical.
3. **Synthesis Friction**: Turning conversational insights into publishing-ready formats or interactive prototypes requires substantial manual drafting effort.
4. **Hardware & Zero-Cost Cloud Constraints**: Development and deployment must operate smoothly on consumer hardware (Windows 11, 8 GB RAM) via local models, while offering seamless zero-code runtime switching to high-speed cloud providers without mandatory paid subscriptions (utilizing Google Gemini's free tier).

### Core Capabilities
- **Grounded Conversational AI**: Subprocess-bridged orchestration via genuine **Pi Coding Agent** (`@earendil-works/pi-coding-agent`), querying local Ollama (`qwen2.5:1.5b`) or cloud Google Gemini (`gemini-2.5-flash`).
- **Podcast RAG with Citations**: Semantic vector search backed by PostgreSQL + `pgvector` and `nomic-embed-text` embeddings. Every claim includes episode titles, guest names, timestamps, and verbatim quotes, with honest refusal when evidence is lacking.
- **Ship 30 for 30 Digital Essay Generator**: Specialized multi-stage writing skill generating ~1,250-word structured essays with skimmable formatting (2–3 sentence paragraphs, bullet points, selective bolding).
- **HTML/CSS Design Artifacts with Sandboxed Live Preview**: Automated generation of landing pages, components, and dashboards rendered in an isolated, security-hardened iframe (`sandbox=""` with strict CSP and custom Python `HTMLParser` server-side sanitization).
- **Session-Based PostgreSQL Persistence**: Full multi-turn conversation histories, essay drafts, and generated HTML/CSS artifacts persisted across browser reloads.
- **Switchable Model Providers**: Runtime switching between Local Ollama and Cloud Google Gemini from an interactive dropdown/selector without restarting servers or rebuilding code.
- **Complete Docker Containerization**: Multi-container Docker Compose stack featuring isolated database volumes, host-gateway networking, and production Nginx reverse proxying.

---

## 2. Architecture Overview

### User Interaction & Agent Orchestration Flow
```mermaid
sequenceDiagram
    autonumber
    actor User as User / Browser
    participant React as React 18 + Vite (Port 5173 / 8080)
    participant FastAPI as FastAPI Backend (Port 8000)
    participant DB as PostgreSQL + pgvector
    participant Pi as Pi Coding Agent (Node.js RPC)
    participant LLM as Ollama / Google Gemini

    User->>React: Submit Prompt / Essay / Artifact Request
    React->>FastAPI: POST /api/sessions/{id}/respond (or /essay, /artifact)
    FastAPI->>DB: Save User Message
    alt RAG Evidence Retrieval Active
        FastAPI->>LLM: Embed Query (nomic-embed-text)
        FastAPI->>DB: Cosine Vector Search (transcript_chunks)
        DB-->>FastAPI: Top-K Grounded Passages & Metadata
    end
    FastAPI->>Pi: Spawn Pi RPC Subprocess with System Prompt & Evidence
    Pi->>LLM: Stream Inference Request (qwen2.5:1.5b or gemini-2.5-flash)
    LLM-->>Pi: Tokens / Content Generation
    Pi-->>FastAPI: JSONL RPC Events (message_update, agent_end)
    FastAPI->>FastAPI: Server-Side HTML Sanitization & Citation Validation
    FastAPI->>DB: Persist Assistant Response & Artifact Metadata
    FastAPI-->>React: Return Structured JSON Response
    React-->>User: Render Message / Citations / Sandboxed Iframe
```

### Knowledge Retrieval (RAG) Architecture
```mermaid
flowchart TD
    A[Lenny's Podcast Transcripts] --> B[Semantic Chunking & Metadata Extraction]
    B --> C[Ollama nomic-embed-text 768d]
    C --> D[(PostgreSQL 17 + pgvector)]
    E[User Growth Question] --> F[Ollama nomic-embed-text]
    F --> G[Cosine Distance Vector Retrieval <=> HNSW/IVFFlat]
    D --> G
    G --> H{Similarity >= Threshold?}
    H -- Yes --> I[Assemble Verbatim Evidence Context & Timestamps]
    H -- No --> J[Flag Insufficient Evidence Advisory]
    I --> K[Pi Coding Agent Prompt Boundary]
    J --> K
```

### Security Boundaries: HTML Artifact Sandboxing
Model-generated HTML/CSS is treated as strictly untrusted:
1. **Server-Side Sanitization**: Cleaned with a dedicated Python `HTMLParser`-based sanitizer enforcing a strict whitelist of safe semantic tags and CSS properties; all `<script>`, `<iframe>`, `<object>`, `<embed>`, SVG markup, inline event handlers (`onclick`, `onload`), and `javascript:` URIs are stripped.
2. **Strict Browser Sandboxing**: Rendered inside an `<iframe sandbox srcdoc="...">` element. The `sandbox` attribute is intentionally empty (`""`), meaning:
   - JavaScript execution is completely disabled (no `allow-scripts`).
   - Same-origin privileges are denied (no `allow-same-origin`), preventing access to cookies, localStorage, or parent DOM.
   - External form submissions and top-level navigation are blocked (no `allow-forms`, no `allow-top-navigation`).
3. **Content Security Policy**: An injected `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">` tag prevents any outbound network requests or external asset loading.

---

## 3. System Prerequisites

Verify that the following tools are installed on your host system:

| Dependency | Minimum Version | Verified Environment | Notes |
| :--- | :--- | :--- | :--- |
| **Operating System** | Windows 10/11, macOS, or Linux | Windows 11 64-bit | Tuned for 8 GB RAM |
| **Python** | 3.11 or 3.12 | Python 3.12.10 | Required for FastAPI backend |
| **Node.js** | `>=22.19.0` (Node 22 LTS) | Node 22.19.0 / npm 10.9.3 | Required by `@earendil-works/pi-coding-agent` |
| **Docker Desktop** | `>=24.0` | Docker 29.7.2 / Compose 5.5.0 | Required for containerized deployment |
| **PostgreSQL** | PostgreSQL 16 or 17 with `pgvector` | Docker container or local instance | Port 5432 or 55432 |
| **Ollama** | `>=0.4.0` | Ollama 0.40.2 | Local model server at `http://localhost:11434` |

### Required Local AI Models (Ollama)
Ensure the following models are pulled into your local Ollama instance:
```bash
ollama pull qwen2.5:1.5b
ollama pull nomic-embed-text
```

---

## 4. Local Development Setup (Manual Runbook)

Follow these steps to run the frontend and backend directly on your host machine.

### Step 1: Configure Environment Variables
Copy `.env.example` to `.env` in the repository root:
```bash
cp .env.example .env
```
*(On Windows PowerShell: `Copy-Item .env.example .env`)*

Review `.env` and verify:
- `DATABASE_URL`: `postgresql+psycopg://postgres:your_password@127.0.0.1:5432/lenny_assistant` (adjust credentials as needed).
- `OLLAMA_BASE_URL`: `http://localhost:11434`
- `OLLAMA_MODEL`: `qwen2.5:1.5b`
- `EMBEDDING_MODEL`: `nomic-embed-text`
- `AGENT_FRAMEWORK`: `pi_agent`
- `GEMINI_API_KEY`: Optional; obtain a free key at [Google AI Studio](https://aistudio.google.com/) for zero-cost cloud inference.

### Step 2: Install Python Virtual Environment & Backend Dependencies
```bash
python -m venv .venv
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# On macOS/Linux:
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

### Step 3: Install Pi Coding Agent Node Runtime
The Pi Coding Agent requires its local Node package in `agent_runtime/`:
```bash
cd agent_runtime
npm install
cd ..
```

### Step 4: Apply Database Migrations
Ensure your PostgreSQL instance is running, then run Alembic migrations from `backend/`:
```bash
cd backend
alembic upgrade head
cd ..
```
*Migrations applied: `0001` (sessions & messages), `0002` (pgvector extension & chunks), `0003` (corpus metadata), `0004` (artifact metadata).*

### Step 5: Start the FastAPI Backend
```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```
Verify backend health:
```bash
curl http://localhost:8000/api/health
```
Interactive Swagger documentation is available at: **`http://localhost:8000/docs`**.

### Step 6: Install Frontend Dependencies & Start Vite Dev Server
In a separate terminal:
```bash
cd frontend
npm install
npm run dev
```
Open your browser at: **`http://localhost:5173`**.

---

## 5. Docker Compose Deployment

The project provides a multi-container Docker configuration (`docker-compose.yml` / `compose.yaml`) optimized for commodity laptops (memory capped at ~2.3 GB RAM total across all containers).

### Services in Stack
1. **`postgres`**: PostgreSQL 17 with `pgvector` extension.
   - Volume: `${DOCKER_POSTGRES_VOLUME:-lenny_compose_postgres_data}` (isolated from development database).
   - Host Port: `127.0.0.1:5432` (configurable via `POSTGRES_PORT`).
2. **`backend`**: FastAPI backend + Node.js 22 LTS runtime for Pi Coding Agent.
   - Host Port: `127.0.0.1:8000` (configurable via `BACKEND_PORT`).
   - Automatically waits for database readiness and applies Alembic migrations on startup via `entrypoint.sh`.
   - Uses `host.docker.internal:11434` to communicate with the host's Ollama instance.
3. **`frontend`**: Production React single-page app built with Vite and served via lightweight Nginx.
   - Host Port: `127.0.0.1:8080` (configurable via `FRONTEND_PORT`).
   - Reverse proxies `/api/*` requests to the backend with extended 960s timeouts for long generations.

### Starting the Docker Stack
```bash
docker compose up --build -d
```

### Verifying Stack Health
```bash
docker compose ps
docker compose logs -f backend
```
Access the containerized application at: **`http://localhost:8080`**.

> [!IMPORTANT]
> **Database Volume Safety**: The Compose stack stores its data in a dedicated named volume (`lenny_compose_postgres_data`), ensuring it will never overwrite, reset, or conflict with any existing Windows-hosted development volume (`lenny_assistant_postgres_data`).
> If you wish to connect the Docker containers to an existing Windows-hosted database, explicitly set `DOCKER_DATABASE_URL` in `.env` (e.g. `postgresql+psycopg://postgres:password@host.docker.internal:55432/lenny_assistant`).

---

## 6. Cloud Provider Configuration (Google Gemini API — Zero-Cost Option)

The Lenny Growth Assistant supports switching between local inference (Ollama) and cloud inference (Google Gemini) directly from the running web interface.

### Enabling Google Gemini (Free Tier)
1. Open your root `.env` file.
2. Provide your Gemini API key (obtainable at [https://aistudio.google.com/](https://aistudio.google.com/)):
   ```env
   GEMINI_API_KEY=your-gemini-api-key-here
   GEMINI_MODEL=gemini-2.5-flash
   ```
3. Restart or reload the FastAPI backend.
4. In the React interface, select **Cloud: Google Gemini (gemini-2.5-flash)** in the header dropdown.
5. Submit your query.

> [!NOTE]
> - Google Gemini free-tier rate limits and availability depend on your Google AI Studio account and project quotas.
> - When `GEMINI_API_KEY` is not configured, the UI clearly displays `[Unconfigured]` and prevents accidental dispatch.
> - Never commit `.env` or paste real API keys into version control. The repository's `.gitignore` and `.dockerignore` strictly exclude all `.env` files.

---

## 7. Reviewer Feature Demonstration Walkthrough

Reviewers can verify all primary capabilities using the following 5-step walkthrough:

### Step 1: Grounded Podcast Q&A with Citations
1. Open the UI at `http://localhost:5173` (or `http://localhost:8080` under Docker).
2. Click **+ New Chat Session**.
3. In the chat input, ask:
   > *"What does Elena Verna recommend regarding when B2B SaaS companies should launch a free trial vs. a freemium model?"*
4. Observe the response: The assistant synthesizes the operational advice and displays an interactive **Citations Drawer** citing the episode title, guest name, timestamp, and verbatim quotes.

### Step 2: Runtime Model Switching
1. In the header bar, click the provider dropdown.
2. Switch to **Cloud: Google Gemini (gemini-2.5-flash)** if configured in `.env`, or verify the unconfigured advisory.
3. Observe that subsequent turns dispatch with the selected provider without requiring any server restart.

### Step 3: Ship 30 for 30 Digital Essay Generation
1. In the header or action bar, click **Generate Essay** (or submit a topic like: *"Top 5 B2B Pricing Mistakes Founders Make"*).
2. The orchestrator executes the multi-stage writing pipeline: outline creation, section drafting, and synthesis.
3. The right-hand **Artifact Viewer** panel automatically opens, displaying the structured ~1,250-word essay with a compelling hook, 2–3 sentence paragraphs, bullet points, and verified takeaways.

### Step 4: HTML/CSS Artifact Generation & Sandboxed Preview
1. Click the **Create HTML Artifact** button in the header.
2. Enter a prompt: *"A modern dark-mode pricing table for a B2B SaaS product with three tiers, feature checklists, and recommended badges"*.
3. Upon completion, the Artifact Viewer displays:
   - **Preview Tab**: The live rendered design in a strictly sandboxed iframe (`sandbox=""`).
   - **HTML Tab**: Formatted, safe HTML source code with one-click copy.
   - **CSS Tab**: Formatted CSS stylesheet with one-click copy.

### Step 5: Session Restoration & Persistence
1. Refresh your browser window.
2. Click on the session in the left-hand sidebar.
3. Verify that all chat messages, citations, Ship 30 essays, and HTML/CSS artifacts are immediately restored from PostgreSQL.

---

## 8. Automated Testing

### Backend Unit & Integration Tests
The backend test suite covers health checks, session management, message validation, RAG retrieval logic, essay orchestration, and HTML artifact sanitization.

Run the test suite:
```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Run full backend test suite
pytest backend/tests/ -v
```

### Frontend Production Build Verification
To verify that the React bundle compiles without errors:
```powershell
cd frontend
npm run build
```

---

## 9. Technical Limitations & Known Tradeoffs

1. **Local Model Quality vs. Hardware Footprint**: The default local model (`qwen2.5:1.5b`) is tuned for consumer hardware (8 GB RAM). While it reliably executes conversational turns, generation quality and reasoning depth on complex multi-stage tasks are naturally more constrained than frontier models.
2. **Local Generation Latency**: On CPU-only systems without dedicated GPU acceleration, generating full ~1,250-word multi-stage essays or detailed HTML layouts with local Ollama may take 60–180 seconds. Cloud inference via Google Gemini Flash is substantially faster (10–25 seconds).
3. **Corpus Embedding Coverage**: The development database contains a curated subset of indexed podcast episodes for local efficiency. Questions outside the indexed episodes will trigger an honest "Insufficient transcript evidence" response.
4. **Deterministic Grounding vs. Factual Accuracy**: Grounding heuristics verify semantic similarity against indexed transcript chunks. While this dramatically suppresses hallucinations, it reflects the opinions of the interviewed podcast guests rather than absolute industry truths.
5. **Defense-in-Depth HTML Sandboxing**: Generated HTML artifacts are sanitized server-side with custom `HTMLParser` logic and displayed in an iframe with `sandbox=""` (scripts disabled). Complex interactive widgets requiring dynamic JavaScript execution are intentionally restricted by design for application security.

---

## 10. Repository File Structure

```text
E:\OogwayLabs\Lenny-Growth-Assistant
├── .dockerignore                 # Excludes .env, .local/, corpus, node_modules, and virtualenvs
├── .env.example                  # Safe configuration template with all provider and port defaults
├── .gitignore                    # Excludes secrets, databases, agent traces, and private local notes
├── compose.yaml                  # Multi-container Compose stack (Postgres + Backend + Frontend)
├── docker-compose.yml            # Standard Compose alias
├── README.md                     # Public project documentation & runbook (this file)
├── PRD.md                        # Product Requirements Document
├── architecture.md               # System Architecture & Technical Specification
├── design.md                     # UI/UX design specifications & design tokens
├── DEMO_RECORDING_GUIDE.md       # 2–3 minute demonstration video recording script
├── SUBMISSION_CHECKLIST.md       # Comprehensive pre-submission verification checklist
│
├── frontend/                     # React 18 + Vite Single Page Application
│   ├── Dockerfile                # Multi-stage production build (Node 20 -> Nginx Alpine)
│   ├── nginx.conf                # Nginx reverse proxy with extended timeouts for AI generation
│   ├── package.json              # React 18, Lucide icons, Vite
│   └── src/
│       ├── api.js                # API client with error handling and timeout budgets
│       ├── App.jsx               # Three-panel workspace shell with resizers and state
│       ├── index.css             # Pure Vanilla CSS design token system (dark slate theme)
│       └── components/           # Modular UI components (Chat, ArtifactViewer, Citations, etc.)
│
├── backend/                      # FastAPI Application Service
│   ├── Dockerfile                # Multi-runtime image (Python 3.11 + Node.js 22 LTS for Pi)
│   ├── entrypoint.sh             # Container startup script (DB wait, migrations, Pi config, uvicorn)
│   ├── requirements.txt          # Backend dependencies (FastAPI, SQLAlchemy, psycopg, etc.)
│   ├── alembic/                  # Database migration version scripts (0001 through 0004)
│   ├── app/
│   │   ├── main.py               # FastAPI entrypoint, CORS, exception handlers, router assembly
│   │   ├── config.py             # Pydantic Settings reading environment variables
│   │   ├── database.py           # SQLAlchemy 2.x engine, connection pool, and session dependency
│   │   ├── agent/                # Pi Coding Agent RPC bridge, RAG pipeline, and skill orchestrators
│   │   ├── models/               # SQLAlchemy ORM models (sessions, messages, chunks)
│   │   ├── schemas/              # Pydantic v2 validation schemas
│   │   └── routes/               # FastAPI routers (sessions, messages, essay, artifact, models, ready)
│   └── tests/                    # Pytest test suite (health, sessions, messages, retrieval, artifacts)
│
├── agent_runtime/                # Local Node.js runtime for Pi Coding Agent
│   ├── package.json              # Declares @earendil-works/pi-coding-agent dependency
│   └── models.json.example       # Example provider configuration for Pi CLI
│
└── agent_transcripts/            # Authentic coding-agent execution evidence
    ├── README.md                 # Authenticity policy and sanitization standards
    └── EVIDENCE_COLLECTION_GUIDE.md # Step-by-step workflow for capturing genuine Pi run traces
```
