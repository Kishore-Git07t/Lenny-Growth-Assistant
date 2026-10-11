# Demonstration Video Recording Guide (2–3 Minutes)
## The Lenny Growth Assistant — Oogway Labs Assessment

This runbook provides the exact script, timing breakdown, screen layout, and talking points for the **2–3 minute demonstration video**.

---

## 1. Recording Setup & Preparation Checklist

- **Camera**: Webcam with presenter on-camera (corner picture-in-picture or full-screen intro/outro).
- **Resolution**: 1080p (1920x1080) at 30/60 fps.
- **Audio**: Clear microphone with background noise suppression.
- **Screen Layout**:
  - Main window: Browser at `http://localhost:5173` (or `http://localhost:8080`).
  - Terminal window (optional/background): Demonstrating backend/Docker services running.
- **Pre-recorded Artifact Recommendation**: Because generating a full 1,250-word essay with local Ollama on CPU can take 60–120 seconds, **generate an essay and an HTML artifact ahead of time in a saved session**. You can show the generation trigger or switch directly to the completed persisted session to keep the demo crisp, engaging, and within the 3-minute limit.

---

## 2. Timing & Sequence Breakdown (Total: ~2 Minutes 45 Seconds)

### Phase 1: On-Camera Introduction (0:00 – 0:25) [25 Seconds]
- **Visual**: Camera full-screen or prominent picture-in-picture.
- **Script**:
  > *"Hi everyone, I'm [Your Name], and this is The Lenny Growth Assistant for the Oogway Labs Forward Deployed Engineer assessment. 
  > The problem we're solving is that while Lenny's Podcast contains world-class growth and product wisdom, off-the-shelf chatbots frequently hallucinate metrics or give generic advice. 
  > We built a full-stack copilot that grounds conversational inquiry in authentic podcast transcripts using pgvector, orchestrates workflows using the genuine Pi Coding Agent, generates publishing-ready Ship 30 for 30 essays, and renders secure HTML/CSS design artifacts in an isolated sandbox."*

### Phase 2: React UI & Grounded Podcast Q&A with Citations (0:25 – 1:05) [40 Seconds]
- **Visual**: Screen recording of the React interface.
- **Action**:
  1. Show the three-panel layout: Session History (left), Chat Workspace (center), and Artifact Viewer (right).
  2. Ask (or click a pre-typed prompt): *"What does Elena Verna recommend regarding when B2B companies should launch a free trial vs. a freemium model?"*
  3. Expand the **Citations Drawer** below the response.
- **Talking Points**:
  > *"Here is the React interface with our dark-slate design system. When we ask a growth question, the backend retrieves semantically matching chunks from PostgreSQL using pgvector and nomic-embed-text. Notice our Citations Drawer: every claim is explicitly attributed with the guest name, episode title, timestamp, and verbatim quotes. If transcripts lack evidence, the assistant honestly refuses rather than hallucinating."*

### Phase 3: Runtime Model & Provider Switching (1:05 – 1:30) [25 Seconds]
- **Visual**: Click the **Model Badge** in the header.
- **Action**: Open the model selector modal showing Local Ollama and Cloud Google Gemini.
- **Talking Points**:
  > *"In the header, you can see our switchable provider architecture. We default to local Ollama running qwen2.5:1.5b for complete offline privacy and zero cost. With one click, users can switch to Google Gemini (gemini-2.5-flash via Google AI Studio's free tier) for rapid cloud generation, without needing any code changes or server restarts."*

### Phase 4: Ship 30 for 30 Essay & Sandboxed Artifact Viewer (1:30 – 2:15) [45 Seconds]
- **Visual**: Right-hand panel opens showing the Ship 30 essay, then switch to the HTML/CSS artifact preview.
- **Action**:
  1. Show the formatted Ship 30 essay (headline hook, 2–3 sentence paragraphs, bullet points, ~1,250 words).
  2. Switch to an HTML/CSS artifact (e.g. B2B Pricing Table).
  3. Toggle between **Preview**, **HTML**, and **CSS** tabs.
  4. Point out the safe iframe isolation.
- **Talking Points**:
  > *"Here is our dedicated Ship 30 for 30 writing skill. It structures transcript insights into a ~1,250-word digital essay with skimmable formatting.
  > On the right is our Sandboxed Artifact Viewer. The Pi Coding Agent also generates responsive HTML and CSS components. Security is paramount here: all model-generated code is sanitized server-side with a strict HTMLParser and rendered in an iframe with strict sandbox attributes—JavaScript is completely disabled, and a restrictive CSP blocks outbound connections."*

### Phase 5: Persistence, Architecture & Wrap-Up (2:15 – 2:45) [30 Seconds]
- **Visual**: Refresh the page to show session persistence in PostgreSQL; return camera to presenter.
- **Action**: Refresh browser, click a past session from the sidebar, and deliver concluding remarks.
- **Talking Points**:
  > *"Everything is persisted in PostgreSQL, so refreshing the browser immediately restores all sessions, citations, and artifacts. The entire stack is containerized with Docker Compose using an isolated volume to protect existing data. 
  > Thank you for reviewing The Lenny Growth Assistant, and I look forward to your feedback!"*

---

## 3. Post-Recording Steps

1. Review the recording to ensure audio is clear and video is within 2–3 minutes.
2. Upload as an **Unlisted** or **Public** video on YouTube (or Loom).
3. Copy the URL for inclusion in your final submission form.
