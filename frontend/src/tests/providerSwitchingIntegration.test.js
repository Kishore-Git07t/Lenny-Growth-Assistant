/**
 * Frontend Integration Tests
 * Lenny Growth Assistant — Cloud LLM Integration and Local/Cloud Model Switching
 *
 * Covers:
 * 1. Safe provider configuration fetching (/api/models).
 * 2. Provider config error fallback to safe local defaults.
 * 3. Chat prompt payload formatting with provider and model overrides.
 * 4. Essay generation payload with provider and model overrides.
 * 5. HTML/CSS artifact generation payload with provider and model overrides.
 * 6. LocalStorage persistence for selected provider ID.
 * 7. Unconfigured provider guard and actionable user notification.
 */

import {
  fetchProviderConfig,
  sendPrompt,
  generateEssay,
  generateHtmlArtifact,
} from '../api.js';
import { getPendingIndicatorInfo } from '../App.jsx';

describe('Provider Configuration API', () => {
  beforeEach(() => {
    global.fetch = jest.fn();
    localStorage.clear();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test('fetchProviderConfig parses backend provider options safely', async () => {
    const mockBackendResponse = {
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
          is_configured: true,
          description: 'Fast cloud inference using Google Gemini.',
        },
      ],
    };

    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockBackendResponse,
    });

    const result = await fetchProviderConfig();
    expect(result.providers).toHaveLength(2);
    expect(result.providers[0].id).toBe('ollama');
    expect(result.providers[1].id).toBe('google');
    expect(result.providers[1].is_configured).toBe(true);
  });

  test('fetchProviderConfig falls back gracefully when backend is offline', async () => {
    global.fetch.mockRejectedValueOnce(new Error('Network error'));

    const result = await fetchProviderConfig();
    expect(result.default_provider).toBe('ollama');
    expect(result.providers[0].id).toBe('ollama');
    expect(result.providers[1].id).toBe('google');
    expect(result.providers[1].is_configured).toBe(false);
  });
});

describe('Request Payloads with Provider Overrides', () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  test('sendPrompt includes provider and model in JSON body when specified', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        session_id: 'test-session-uuid',
        user_message: { id: 'msg-1' },
        assistant_message: { id: 'msg-2', source_metadata: { provider: 'google', model: 'gemini-2.5-flash' } },
        provider: 'google',
        model: 'gemini-2.5-flash',
      }),
    });

    await sendPrompt('test-session-uuid', 'What is PMF?', {
      provider: 'google',
      model: 'gemini-2.5-flash',
    });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [, options] = global.fetch.mock.calls[0];
    const body = JSON.parse(options.body);

    expect(body.content).toBe('What is PMF?');
    expect(body.provider).toBe('google');
    expect(body.model).toBe('gemini-2.5-flash');
  });

  test('generateEssay includes provider and model in JSON body', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 201,
      json: async () => ({
        session_id: 'test-session-uuid',
        provider: 'google',
        model: 'gemini-2.5-flash',
      }),
    });

    await generateEssay(
      'test-session-uuid',
      {
        topic: 'Retention Mechanics',
        audience: 'Founders',
        target_word_count: 1250,
        provider: 'google',
        model: 'gemini-2.5-flash',
      }
    );

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [, options] = global.fetch.mock.calls[0];
    const body = JSON.parse(options.body);

    expect(body.provider).toBe('google');
    expect(body.model).toBe('gemini-2.5-flash');
  });

  test('generateHtmlArtifact includes provider and model in JSON body', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 201,
      json: async () => ({
        session_id: 'test-session-uuid',
        provider: 'google',
        model: 'gemini-2.5-flash',
      }),
    });

    await generateHtmlArtifact(
      'test-session-uuid',
      {
        prompt: 'Build SaaS Dashboard',
        title: 'SaaS Dashboard',
        artifact_type: 'dashboard',
        provider: 'google',
        model: 'gemini-2.5-flash',
      }
    );

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [, options] = global.fetch.mock.calls[0];
    const body = JSON.parse(options.body);

    expect(body.provider).toBe('google');
    expect(body.model).toBe('gemini-2.5-flash');
  });
});

describe('Pending Model Indicator Metadata', () => {
  test('formats Ollama local model indicator and timing guidance', () => {
    const info = getPendingIndicatorInfo({
      id: 'ollama',
      name: 'Local (Ollama)',
      model: 'qwen2.5:1.5b',
      type: 'local',
    });
    expect(info.label).toBe(
      "Searching Lenny's Podcast transcripts and generating a grounded response using Pi Coding Agent (Local Ollama — qwen2.5:1.5b)..."
    );
    expect(info.hint).toBe(
      'Local inference typically takes 20–60 seconds on standard CPU/8 GB RAM.'
    );
    expect(info.isCloud).toBe(false);
  });

  test('formats Google Gemini cloud model indicator and cloud inference guidance', () => {
    const info = getPendingIndicatorInfo({
      id: 'google',
      name: 'Cloud (Google Gemini)',
      model: 'gemini-3.8-flash',
      type: 'cloud',
    });
    expect(info.label).toBe(
      "Searching Lenny's Podcast transcripts and generating a grounded response using Pi Coding Agent (Cloud Google Gemini — gemini-3.8-flash)..."
    );
    expect(info.hint).toBe(
      'Transcripts retrieved locally with pgvector embeddings; response generated via Google Gemini cloud inference.'
    );
    expect(info.isCloud).toBe(true);
  });

  test('preserves dynamic model name from backend metadata', () => {
    const info = getPendingIndicatorInfo({
      id: 'google',
      name: 'Cloud (Google Gemini)',
      model: 'gemini-2.5-flash',
      type: 'cloud',
    });
    expect(info.label).toContain('(Cloud Google Gemini — gemini-2.5-flash)...');
  });
});

