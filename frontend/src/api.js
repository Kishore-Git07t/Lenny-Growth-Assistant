/**
 * API client module for Lenny Growth Assistant.
 * Connects React frontend directly to the FastAPI backend via Vite proxy (/api).
 */

const BASE_URL = '';

/**
 * Handle API responses and normalize error payloads.
 * @param {Response} response
 * @returns {Promise<any>}
 */
async function handleResponse(response) {
  if (!response.ok) {
    let errorMessage = `HTTP ${response.status} ${response.statusText}`;
    try {
      const data = await response.json();
      if (typeof data.detail === 'string') {
        errorMessage = data.detail;
      } else if (Array.isArray(data.detail)) {
        errorMessage = data.detail
          .map((item) => item.msg || item.message || JSON.stringify(item))
          .join('; ');
      } else if (data.detail && typeof data.detail === 'object') {
        errorMessage = data.detail.message || data.detail.error || JSON.stringify(data.detail);
      } else if (data.message) {
        errorMessage = data.message;
      }
    } catch {
      // Body was not JSON
    }
    const error = new Error(errorMessage);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

/**
 * Validate an essay topic string according to Ship 30 and backend schema rules.
 * @param {string} topic
 * @returns {string|null} Error message or null if valid
 */
export function validateEssayTopic(topic) {
  const trimmed = topic ? topic.trim() : '';
  if (!trimmed) return 'Please enter an essay topic.';
  if (trimmed.length < 3) return 'Topic must be at least 3 characters long.';
  return null;
}

/**
 * Check backend health status.
 * @returns {Promise<{ status: string, service: string, version: string, llm_provider: string, model: string }>}
 */
export async function fetchHealth() {
  const response = await fetch(`${BASE_URL}/api/health`, {
    headers: { Accept: 'application/json' },
  });
  return handleResponse(response);
}

/**
 * List saved chat sessions ordered by updated_at descending.
 * @param {number} limit
 * @param {number} offset
 * @returns {Promise<{ items: Array, total: number, limit: number, offset: number }>}
 */
export async function fetchSessions(limit = 50, offset = 0) {
  const response = await fetch(`${BASE_URL}/api/sessions?limit=${limit}&offset=${offset}`, {
    headers: { Accept: 'application/json' },
  });
  return handleResponse(response);
}

/**
 * Create a new conversation session.
 * @param {string|null} title
 * @param {object} userMetadata
 * @returns {Promise<{ id: string, title: string|null, user_metadata: object, created_at: string, updated_at: string }>}
 */
export async function createSession(title = null, userMetadata = {}) {
  const response = await fetch(`${BASE_URL}/api/sessions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({
      title: title || undefined,
      user_metadata: userMetadata || {},
    }),
  });
  return handleResponse(response);
}

/**
 * Retrieve a single session by its UUID.
 * @param {string} sessionId
 * @returns {Promise<{ id: string, title: string|null, user_metadata: object, created_at: string, updated_at: string }>}
 */
export async function fetchSession(sessionId) {
  const response = await fetch(`${BASE_URL}/api/sessions/${sessionId}`, {
    headers: { Accept: 'application/json' },
  });
  return handleResponse(response);
}

/**
 * Update an existing conversation session's title or user_metadata.
 * @param {string} sessionId
 * @param {{ title?: string, user_metadata?: object }} payload
 * @returns {Promise<{ id: string, title: string|null, user_metadata: object, created_at: string, updated_at: string }>}
 */
export async function updateSession(sessionId, payload) {
  const response = await fetch(`${BASE_URL}/api/sessions/${sessionId}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(payload),
  });
  return handleResponse(response);
}

/**
 * Retrieve message history for a conversation session.
 * @param {string} sessionId
 * @param {number} limit
 * @param {number} offset
 * @returns {Promise<{ items: Array, total: number, limit: number, offset: number }>}
 */
export async function fetchMessages(sessionId, limit = 100, offset = 0) {
  const response = await fetch(
    `${BASE_URL}/api/sessions/${sessionId}/messages?limit=${limit}&offset=${offset}`,
    {
      headers: { Accept: 'application/json' },
    }
  );
  return handleResponse(response);
}

/**
 * Save a raw user message without triggering assistant generation.
 * @param {string} sessionId
 * @param {string} content
 * @returns {Promise<object>}
 */
export async function postUserMessage(sessionId, content) {
  const response = await fetch(`${BASE_URL}/api/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ content }),
  });
  return handleResponse(response);
}

/**
 * Fetch available LLM provider capabilities and configuration status.
 * Never exposes server API keys or secrets.
 * @returns {Promise<{
 *   default_provider: string,
 *   active_provider: string,
 *   providers: Array<{
 *     id: string,
 *     name: string,
 *     model: string,
 *     type: 'local'|'cloud',
 *     is_configured: boolean,
 *     description: string
 *   }>
 * }>}
 */
export async function fetchProviderConfig() {
  try {
    const response = await fetch(`${BASE_URL}/api/models`, {
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) {
      throw new Error(`Failed to load model config: HTTP ${response.status}`);
    }
    return await response.json();
  } catch (err) {
    // Safe offline fallback defaults matching system architecture
    return {
      default_provider: 'ollama',
      active_provider: 'ollama',
      providers: [
        {
          id: 'ollama',
          name: 'Local (Ollama)',
          model: 'qwen2.5:1.5b',
          type: 'local',
          is_configured: true,
          description: 'Offline local inference using Ollama with genuine Pi Coding Agent.',
        },
        {
          id: 'google',
          name: 'Cloud (Google Gemini)',
          model: 'gemini-2.5-flash',
          type: 'cloud',
          is_configured: false,
          description: 'Google Gemini is not configured. Set GEMINI_API_KEY in the server .env to enable (free tier available via Google AI Studio).',
        },
      ],
    };
  }
}

/**
 * Send a question to the grounded RAG endpoint and generate an assistant response.
 * Local Ollama + Pi Agent may take 20-60+ seconds, so timeout defaults to 120s.
 *
 * @param {string} sessionId
 * @param {string} content
 * @param {{ timeoutMs?: number, provider?: string|null, model?: string|null }} options
 * @returns {Promise<{
 *   session_id: string,
 *   user_message: object,
 *   assistant_message: object,
 *   provider: string,
 *   model: string,
 *   retried: boolean,
 *   citations: Array,
 *   retrieval_status: string,
 *   coverage: object,
 *   disclaimer: string|null
 * }>}
 */
export async function sendPrompt(
  sessionId,
  content,
  { timeoutMs = 120000, provider = null, model = null } = {}
) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const requestBody = { content };
  if (provider) requestBody.provider = provider;
  if (model) requestBody.model = model;

  try {
    const response = await fetch(`${BASE_URL}/api/sessions/${sessionId}/respond`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(requestBody),
      signal: controller.signal,
    });
    return await handleResponse(response);
  } catch (err) {
    if (err.name === 'AbortError') {
      const timeoutError = new Error(
        'Request timed out waiting for AI agent response (exceeded 120s). ' +
        'Ollama, OpenAI, or Pi Coding Agent may still be processing. Please reload session history to check.'
      );
      timeoutError.status = 504;
      timeoutError.isTimeout = true;
      throw timeoutError;
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Generate a ~1,250-word Ship 30 for 30 digital essay artifact from podcast transcripts.
 * Because the local Ollama model generates multi-stage outlines and 5 structured sections,
 * generation may take several minutes on CPU/GPU. Client-side timeout defaults to 16 minutes (960,000 ms),
 * providing reasonable response overhead beyond the backend's 15-minute generation budget.
 *
 * @param {string} sessionId
 * @param {{ topic: string, audience?: string|null, target_word_count?: number }} payload
 * @param {{ timeoutMs?: number, signal?: AbortSignal }} options
 * @returns {Promise<{
 *   session_id: string,
 *   message_id: string|null,
 *   artifact_type: string,
 *   title: string,
 *   topic: string,
 *   audience: string,
 *   content: string,
 *   word_count: number,
 *   target_word_count: number,
 *   status: string,
 *   provider: string,
 *   model: string,
 *   citations: Array,
 *   coverage: object|null,
 *   disclaimer: string|null,
 *   created_at: string
 * }>}
 */
export async function generateEssay(
  sessionId,
  payload,
  { timeoutMs = 960000, signal = null } = {}
) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  // Propagate external abort signal if provided
  if (signal) {
    signal.addEventListener('abort', () => controller.abort(), { once: true });
  }

  try {
    const response = await fetch(`${BASE_URL}/api/sessions/${sessionId}/essay`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({
        topic: payload.topic.trim(),
        audience: payload.audience ? payload.audience.trim() : null,
        target_word_count: payload.target_word_count || 1250,
        provider: payload.provider || undefined,
        model: payload.model || undefined,
      }),
      signal: controller.signal,
    });
    return await handleResponse(response);
  } catch (err) {
    if (err.name === 'AbortError') {
      const timeoutError = new Error(
        'Request timed out waiting for essay generation (exceeded 16 minutes). ' +
        'Ollama or Pi Coding Agent may still be completing sections in the background. ' +
        'Timing out in the browser does not necessarily stop server-side processing. ' +
        'Please refresh or re-check this session in a moment.'
      );
      timeoutError.status = 504;
      timeoutError.isTimeout = true;
      throw timeoutError;
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Retrieve the latest persisted Ship 30 for 30 essay artifact for a conversation session.
 * Returns null if no essay has been generated yet for this session (HTTP 404).
 *
 * @param {string} sessionId
 * @param {{ signal?: AbortSignal }} options
 * @returns {Promise<object|null>}
 */
export async function fetchLatestEssay(sessionId, { signal = null } = {}) {
  const response = await fetch(`${BASE_URL}/api/sessions/${sessionId}/essay`, {
    headers: { Accept: 'application/json' },
    signal,
  });

  if (response.status === 404) {
    // Expected when session has no saved essay
    return null;
  }

  return handleResponse(response);
}

/**
 * Validate an HTML artifact prompt according to backend schema rules.
 * @param {string} prompt
 * @returns {string|null} Error message or null if valid
 */
export function validateArtifactPrompt(prompt) {
  const trimmed = prompt ? prompt.trim() : '';
  if (!trimmed) return 'Please describe the webpage or component you want to create.';
  if (trimmed.length < 5) return 'Description must be at least 5 characters long.';
  if (trimmed.length > 4000) return 'Description cannot exceed 4,000 characters.';
  return null;
}

/**
 * Generate a professional, sanitized HTML/CSS design artifact using Pi Coding Agent.
 * Client-side timeout defaults to 4 minutes (240,000 ms), matching backend budget plus network overhead.
 *
 * @param {string} sessionId
 * @param {{
 *   prompt: string,
 *   title?: string|null,
 *   artifact_type?: string,
 *   style_preferences?: string|null,
 *   include_podcast_context?: boolean
 * }} payload
 * @param {{ timeoutMs?: number, signal?: AbortSignal }} options
 * @returns {Promise<{
 *   artifact_id: string,
 *   session_id: string,
 *   title: string,
 *   artifact_type: string,
 *   prompt: string,
 *   html: string,
 *   css: string,
 *   combined_preview: string,
 *   status: string,
 *   created_at: string,
 *   diagnostics: Array<string>,
 *   citations: Array,
 *   coverage: object|null,
 *   disclaimer: string|null
 * }>}
 */
export async function generateHtmlArtifact(
  sessionId,
  payload,
  { timeoutMs = 240000, signal = null } = {}
) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  if (signal) {
    signal.addEventListener('abort', () => controller.abort(), { once: true });
  }

  try {
    const response = await fetch(`${BASE_URL}/api/sessions/${sessionId}/artifact`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({
        prompt: payload.prompt.trim(),
        title: payload.title && payload.title.trim() ? payload.title.trim() : undefined,
        artifact_type: payload.artifact_type ? payload.artifact_type.trim() : 'landing_page',
        style_preferences: payload.style_preferences && payload.style_preferences.trim() ? payload.style_preferences.trim() : undefined,
        include_podcast_context: payload.include_podcast_context !== undefined ? Boolean(payload.include_podcast_context) : true,
        provider: payload.provider || undefined,
        model: payload.model || undefined,
      }),
      signal: controller.signal,
    });
    return await handleResponse(response);
  } catch (err) {
    if (err.name === 'AbortError') {
      const timeoutError = new Error(
        'Request timed out waiting for HTML/CSS artifact generation (exceeded 4 minutes). ' +
        'Pi Coding Agent may still be completing layout in the background. ' +
        'Timing out in the browser does not stop server-side generation. ' +
        'Please refresh or re-check this session in a moment.'
      );
      timeoutError.status = 504;
      timeoutError.isTimeout = true;
      throw timeoutError;
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Retrieve the latest persisted HTML/CSS artifact for a conversation session.
 * Returns null if no HTML artifact has been generated yet for this session (HTTP 404).
 *
 * @param {string} sessionId
 * @param {{ signal?: AbortSignal }} options
 * @returns {Promise<object|null>}
 */
export async function fetchLatestHtmlArtifact(sessionId, { signal = null } = {}) {
  const response = await fetch(`${BASE_URL}/api/sessions/${sessionId}/artifact`, {
    headers: { Accept: 'application/json' },
    signal,
  });

  if (response.status === 404) {
    // Expected when session has no saved HTML artifact
    return null;
  }

  return handleResponse(response);
}

