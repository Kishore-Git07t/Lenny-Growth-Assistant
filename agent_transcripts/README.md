# Coding Agent Transcripts & Audit Trail (`agent_transcripts/`)

This directory stores **sanitized, authentic interaction transcripts** from autonomous and semi-autonomous coding agents (such as Google Antigravity, Pi Coding Agent, and Claude Agent SDK) utilized during the development of the Lenny Growth Assistant.

## Strict Authenticity & Integrity Policy

1. **Genuine Records Only**:
   - Every transcript preserved in this directory reflects authentic development sessions, real execution attempts, actual failures, tool errors, syntax corrections, and iterative architectural refactors.
   - **Never fabricate or simulate agent interactions, test results, or debugging histories.** Honest error trails and recovery strategies demonstrate genuine problem-solving and senior engineering competence.

2. **Capturing Real Failures and Corrections**:
   - Failed tool calls, environment mismatches (e.g., Windows pathing quirks, memory limits under 8 GB RAM), model hallucinations or latency timeouts, and agent corrections are high-value evaluation artifacts and must be retained.
   - For each failed attempt, record the root cause, the correction prompt, and the resulting working state.

## Sanitization Standards

Before committing any transcript to this directory, it must be rigorously sanitized:
- **API Keys & Secrets**: Strip or replace all API keys, bearer tokens, passwords, and private hashes with standard placeholders (e.g., `sk-ant-REDACTED`, `REDACTED_API_KEY`).
- **Internal IP Addresses & Hostnames**: Mask internal corporate hostnames or private IPs (localhost / 127.0.0.1 may remain).
- **Absolute Local Paths**: When personal user directories contain private or identifying usernames, normalize paths (e.g., `C:\Users\<USER>\...` or `E:\DevTools\...`).
- **Confidential Prompt Artifacts**: Remove any confidential assessment PDFs or proprietary evaluation rubric texts if embedded in initial system prompts.

## Recommended Transcript File Naming Convention

- `session_<phase>_<step>_<task-name>.md` (e.g., `session_p1_s1_init_and_scaffolding.md`)
- `session_<phase>_debugging_<issue-description>.md` (e.g., `session_p2_debugging_ollama_qwen_timeout.md`)

## Transcript Structure Template

```markdown
# Agent Session: [Task or Problem Description]
- **Date & Time**: YYYY-MM-DD HH:MM
- **Agent Framework / Model**: Google Antigravity (Gemini 3.8 Flash / Claude 3.5 Sonnet / Pi Agent)
- **Goal**: [Clear statement of the objective]

### Initial Prompt / Task Formulation
...

### Agent Tool Calls & Executions
...

### Failures, Friction & Unexpected Behaviors
- **Encountered**: [e.g., memory constraint, RPC timeout]
- **Correction Applied**: [e.g., streaming chunk adjustments, prompt tuning]

### Resolution & Verified State
...
```
