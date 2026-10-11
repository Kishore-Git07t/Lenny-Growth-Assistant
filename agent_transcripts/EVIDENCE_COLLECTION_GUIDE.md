# Genuine Pi Coding Agent Evidence Collection & Verification Guide

This guide details the procedure for capturing, verifying, sanitizing, and reviewing authentic execution traces from the **Pi Coding Agent** in the **Lenny Growth Assistant**.

---

## 1. Strict Authenticity Policy

- **Zero Fabrication**: Never fabricate tool calls, JSONL RPC events, token streams, or execution logs. An authentic error message or partial recovery is infinitely more valuable and honest than simulated synthetic output.
- **Illustrative JSON is NOT Evidence**: Code snippets or illustrative example JSON in documentation are instructional only and **never acceptable as execution evidence**. Reviewers require verifiable artifacts captured from genuine subprocess executions.
- **Genuine Agent vs. Direct LLM**: Reviewers must be able to verify that turns were executed via the **Pi Coding Agent JSONL RPC bridge** rather than a raw direct REST call to Ollama or Google Gemini.
- **Automated Redaction & Safe Directory**: The evidence collector automatically redacts API keys, tokens, and local usernames, saving evidence to `.local/pi-evidence/` (Git-ignored). Raw traces are **never automatically published** to `agent_transcripts/`.
- **Current Evidence Status**: **No authentic transcript has been committed yet.** The opt-in capture mechanism is fully implemented and awaits intentional manual execution by the reviewer or developer.

---

## 2. Distinguishing Genuine Pi RPC Execution from Direct LLM Calls

When the Lenny Growth Assistant invokes the Pi Coding Agent, the execution exhibits distinct architectural characteristics that do not exist in direct LLM completions:

| Attribute | Direct LLM Call (Diagnostic Only) | Genuine Pi Coding Agent Execution |
| :--- | :--- | :--- |
| **Execution Protocol** | Single HTTP POST to `/api/generate` or `/v1/chat/completions` | Stdio JSONL streaming RPC via Node.js subprocess (`@earendil-works/pi-coding-agent`) |
| **Agent Event Stream** | Raw text tokens or standard SSE chunks | Structured JSONL messages: `response`, `agent_start`, `turn_start`, `message_update`, `turn_end`, `agent_end`, `agent_settled` |
| **Tool Calling Surface** | Direct API function-calling parameters | Pi tool calling framework with explicit parameter schemas, lifecycle hooks, and tool boundaries |
| **Configuration & Models** | Application config variables only | Discovers `.local/pi-agent/models.json` via `PI_CODING_AGENT_DIR` |
| **Process Tree** | Single Python process (`uvicorn`) | Python `uvicorn` parent process spawning Node.js child process (`node .../dist/cli.js` or `pi.cmd`) with stdio pipes |
| **CLI Invocation Flags** | None | `--mode rpc --no-session --no-tools --no-extensions --no-skills --no-prompt-templates --no-mcp --no-context-files --provider <prov> --model <model>` |

---

## 3. How the Opt-In Evidence Capture Mechanism Works

The backend provides a safe, minimal, opt-in capture mechanism implemented in:
- `backend/app/agent/pi_client.py`
- `backend/app/agent/evidence_collector.py`
- `backend/app/config.py` (`PI_CAPTURE_EVENTS` and `PI_EVIDENCE_DIR`)

### Core Architecture:
1. **Disabled by Default**: Setting `PI_CAPTURE_EVENTS=false` (the default) ensures zero file I/O overhead during standard operation and automated testing.
2. **Direct RPC Stream Interception**: When enabled, the collector captures raw JSONL records directly as they stream from `proc.stdout.readline()`.
3. **Ordering & Type Preservation**: Events are preserved in their exact order of emission with genuine `type` tags (`agent_start`, `turn_start`, `message_update`, `message_end`, `agent_settled`, etc.).
4. **Real Provider & Model Attribution**: Records the genuine provider (`google` or `ollama`) and model (`gemini-2.5-flash` or `qwen2.5:1.5b`) validated and passed to the child process.
5. **No Tool Fabrication**: If the execution did not invoke tools, `has_tool_invocations` is strictly `false` and `genuine_tools_used` is empty. Tool calls are never invented.
6. **Strict Sanitization**: Automatically scrubs API keys (`AIza...`, `sk-...`, `Bearer ...`), passwords, local Windows usernames (`C:\Users\<USER>`), and project root paths.
7. **Failure Isolation**: Disk write errors or serialization issues are caught and logged; they **never interrupt or break application requests**.

---

## 4. Step-by-Step Manual Capture Workflow

Follow this procedure when ready to capture authentic evidence:

### Step 1: Enable Evidence Capture
In your `.env` file (or temporary shell environment):
```ini
PI_CAPTURE_EVENTS=true
PI_EVIDENCE_DIR=.local/pi-evidence
```

Or in PowerShell:
```powershell
$env:PI_CAPTURE_EVENTS="true"
```

### Step 2: Check Port Availability & Start the Backend
> [!NOTE]
> Existing development ports may already be occupied (e.g. `8000`, `8080`, `8081`, `5173`, `5432`, `11434`) if Docker Compose or previous servers are running. Check your active ports before binding.

If running outside Docker:
```powershell
& ".\.venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

### Step 3: Trigger a Real Generation Turn
Trigger one real generation using either Google Gemini (Cloud) or Ollama (Local):

#### Option A: Via Web UI (`http://localhost:5173` or `http://localhost:8080`)
1. Ensure a conversation session is active.
2. Select provider:
   - **Google Gemini**: Select `Cloud / Google Gemini` (requires `GEMINI_API_KEY` in `.env`).
   - **Local Ollama**: Select `Local / Ollama` with `qwen2.5:1.5b`.
3. Submit a grounded question:
   > *"What does Elena Verna recommend regarding when B2B SaaS companies should launch a free trial vs. freemium model?"*

#### Option B: Via Direct REST API
```powershell
# Create session
$session = Invoke-RestMethod -Uri "http://localhost:8000/api/sessions" -Method Post -ContentType "application/json" -Body '{"title":"Evidence Capture Session"}'
$sessionId = $session.id

# Submit prompt
Invoke-RestMethod -Uri "http://localhost:8000/api/sessions/$sessionId/prompt" -Method Post -ContentType "application/json" -Body '{"prompt":"How should early-stage startups design growth loops according to Lenny?"}'
```

### Step 4: Verify Locally Captured Evidence Files
Locally captured traces appear in the Git-ignored directory:
```text
.local/pi-evidence/
├── pi_rpc_20261011_120000_req-a1b2c3d4.json  # Structured allowlisted event log
└── pi_rpc_20261011_120000_req-a1b2c3d4.md    # Human-readable audit report
```

### Step 5: Inspect and Sanitize Before Publishing
Before copying any trace into the public `agent_transcripts/` directory:
1. Open the generated `.json` and `.md` files in `.local/pi-evidence/`.
2. Verify that:
   - No real API keys, bearer tokens, or secrets are present (all should be `[REDACTED_API_KEY]`).
   - No local personal usernames are visible (should be `C:\Users\<USER>\...`).
   - The event stream contains authentic lifecycle events (`response`, `agent_start`, `turn_start`, etc.).
   - Tool invocations truthfully reflect whether tools were invoked.
3. Intentionally copy the sanitized file to `agent_transcripts/`:
   ```powershell
   Copy-Item .local\pi-evidence\pi_rpc_*.md agent_transcripts\session_genuine_pi_execution.md
   ```

---

## 5. Security & Verification Checklist

- [x] **Git-Ignored Local Directory**: Traces are written to `.local/pi-evidence/`, protected by root `.gitignore` (`.local/`).
- [x] **Zero Synthetic Placeholders**: Traces reflect genuine subprocess output only.
- [x] **Allowlisted Metadata**: Only safe fields (`type`, `command`, `turn_id`, `stopReason`, `role`, etc.) are captured.
- [x] **Graceful Error Handling**: Evidence logging failures never crash the agent or HTTP request.
