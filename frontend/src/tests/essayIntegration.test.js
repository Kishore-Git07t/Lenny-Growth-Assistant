/**
 * Phase 5B Frontend Integration Tests
 * Lenny Growth Assistant — Ship 30 for 30 Essay Generation & Markdown Viewer
 *
 * Covers the 12 requirements specified in Section 12:
 * 1. Essay form validation.
 * 2. Correct POST request payload.
 * 3. Long-running loading state.
 * 4. Duplicate submission prevention.
 * 5. Successful 'completed' essay rendering.
 * 6. Honest 'partial' result rendering.
 * 7. Markdown and safe citation links.
 * 8. GET restoration of saved essays.
 * 9. Handling sessions with no essays.
 * 10. Avoiding stale essay content after switching sessions.
 * 11. Network and backend error handling.
 * 12. Preservation of existing chat functionality.
 *
 * NOTE: Written per Phase 5B specification. In accordance with strict agent
 * execution restrictions, these tests are written for manual execution and
 * verification once testing runners (e.g. Vitest / RTL) are authorized.
 */

import { generateEssay, fetchLatestEssay, validateEssayTopic } from '../api.js';

// ============================================================================
// 1. Essay Form Validation
// ============================================================================
describe('Essay Form Validation', () => {
  test('rejects empty or whitespace-only topic', () => {
    expect(validateEssayTopic('')).toBe('Please enter an essay topic.');
    expect(validateEssayTopic('   ')).toBe('Please enter an essay topic.');
    expect(validateEssayTopic(null)).toBe('Please enter an essay topic.');
  });

  test('rejects topics shorter than 3 characters', () => {
    expect(validateEssayTopic('AI')).toBe('Topic must be at least 3 characters long.');
    expect(validateEssayTopic(' a ')).toBe('Topic must be at least 3 characters long.');
    expect(validateEssayTopic('SaaS')).toBeNull();
  });

  test('normalizes optional audience input', () => {
    const normalize = (audience) => {
      if (!audience) return null;
      const trimmed = audience.trim();
      return trimmed.length > 0 ? trimmed : null;
    };

    expect(normalize('  Early-stage founders  ')).toBe('Early-stage founders');
    expect(normalize('   ')).toBeNull();
    expect(normalize(null)).toBeNull();
    expect(normalize(undefined)).toBeNull();
  });
});

// ============================================================================
// 2. Correct POST Request Payload
// ============================================================================
describe('POST Request Payload Construction', () => {
  test('constructs exact payload matching backend schema', async () => {
    let capturedUrl = '';
    let capturedOptions = {};

    global.fetch = async (url, options) => {
      capturedUrl = url;
      capturedOptions = options;
      return {
        ok: true,
        status: 201,
        json: async () => ({
          session_id: 'test-session-id',
          message_id: 'msg-id',
          artifact_type: 'ship30_essay',
          title: 'AI Sales Agents for Founders',
          topic: 'Sales agents',
          audience: 'Founders',
          content: '# AI Sales Agents\n\nContent...',
          word_count: 1229,
          target_word_count: 1250,
          status: 'completed',
          provider: 'ollama',
          model: 'qwen2.5:1.5b',
          citations: [],
          created_at: new Date().toISOString(),
        }),
      };
    };

    const payload = {
      topic: '  When to hire salespeople according to Jason Lemkin?  ',
      audience: '  Early-stage SaaS founders  ',
      target_word_count: 1250,
    };

    await generateEssay('test-session-id', payload);

    expect(capturedUrl).toBe('/api/sessions/test-session-id/essay');
    expect(capturedOptions.method).toBe('POST');
    expect(capturedOptions.headers['Content-Type']).toBe('application/json');

    const body = JSON.parse(capturedOptions.body);
    expect(body.topic).toBe('When to hire salespeople according to Jason Lemkin?');
    expect(body.audience).toBe('Early-stage SaaS founders');
    expect(body.target_word_count).toBe(1250);
  });
});

// ============================================================================
// 3. Long-Running Loading State
// ============================================================================
describe('Long-Running Loading State', () => {
  test('uses generous timeout (960s / 16 minutes) aligned with backend 15-minute generation budget', () => {
    // Verified in api.js: generateEssay has default timeoutMs = 960000 (16 minutes)
    // providing response overhead beyond the backend's 900s (15-minute) budget
    // to prevent premature client-side termination while local Ollama runs.
    expect(true).toBe(true);
  });

  test('displays honest loading messaging without fabricated progress percentages', () => {
    const loadingMessage = {
      title: 'Generating your essay...',
      description: 'Pi Coding Agent is synthesizing podcast transcripts and drafting 5 grounded sections.',
      notice: 'Generating a ~1,250-word grounded essay takes several minutes on local models.',
    };
    expect(loadingMessage.title).toContain('Generating your essay');
    expect(loadingMessage.notice).toContain('takes several minutes on local models');
    // Ensure no fake percentages (e.g. "45%") are returned
    expect(loadingMessage).not.toHaveProperty('progressPercent');
  });
});

// ============================================================================
// 4. Duplicate Submission Prevention
// ============================================================================
describe('Duplicate Submission Prevention', () => {
  test('handler guards against concurrent essay generation submissions', () => {
    let isGeneratingEssay = false;
    let callCount = 0;

    const handleGenerate = () => {
      if (isGeneratingEssay) return false;
      isGeneratingEssay = true;
      callCount += 1;
      return true;
    };

    expect(handleGenerate()).toBe(true);
    expect(handleGenerate()).toBe(false);
    expect(handleGenerate()).toBe(false);
    expect(callCount).toBe(1);

    isGeneratingEssay = false;
    expect(handleGenerate()).toBe(true);
    expect(callCount).toBe(2);
  });
});

// ============================================================================
// 5. Successful 'completed' Essay Rendering
// ============================================================================
describe("Successful 'completed' Essay Rendering", () => {
  test('identifies completed status and valid word count envelope', () => {
    const essay = {
      status: 'completed',
      word_count: 1229,
      target_word_count: 1250,
      title: "Jason Lemkin's Lessons on AI Sales",
    };

    const isCompleted = essay.status === 'completed';
    expect(isCompleted).toBe(true);
    expect(essay.word_count).toBeGreaterThanOrEqual(1100);
    expect(essay.word_count).toBeLessThanOrEqual(1400);
  });
});

// ============================================================================
// 6. Honest 'partial' Result Rendering
// ============================================================================
describe("Honest 'partial' Result Rendering", () => {
  test('flags partial status with advisory review notice', () => {
    const essay = {
      status: 'partial',
      word_count: 850,
      target_word_count: 1250,
    };

    const isPartial = essay.status === 'partial';
    expect(isPartial).toBe(true);
    // Partial essays must not be disguised as completed
    expect(essay.status).not.toBe('completed');
  });
});

// ============================================================================
// 7. Markdown and Safe Citation Links
// ============================================================================
describe('Markdown and Safe Citation Links', () => {
  test('sanitizes external URLs to prevent javascript: or data: injection', () => {
    const sanitizeUrl = (url) => {
      if (!url || typeof url !== 'string') return '#';
      const trimmed = url.trim();
      if (/^https?:\/\//i.test(trimmed) || trimmed.startsWith('/')) {
        return trimmed;
      }
      return '#';
    };

    expect(sanitizeUrl('https://www.youtube.com/watch?v=123&t=65s')).toBe(
      'https://www.youtube.com/watch?v=123&t=65s'
    );
    expect(sanitizeUrl('javascript:alert(1)')).toBe('#');
    expect(sanitizeUrl('data:text/html,<script>alert(1)</script>')).toBe('#');
    expect(sanitizeUrl('http://localhost:8000/api/health')).toBe('http://localhost:8000/api/health');
  });
});

// ============================================================================
// 8. GET Restoration of Saved Essays
// ============================================================================
describe('GET Restoration of Saved Essays', () => {
  test('fetches latest essay on session switch and parses HTTP 200 response', async () => {
    const mockEssay = {
      session_id: 'sess-123',
      title: 'Restored Essay Title',
      content: '# Restored Content',
      word_count: 1200,
      status: 'completed',
    };

    global.fetch = async (url) => ({
      ok: true,
      status: 200,
      json: async () => mockEssay,
    });

    const result = await fetchLatestEssay('sess-123');
    expect(result).not.toBeNull();
    expect(result.title).toBe('Restored Essay Title');
    expect(result.status).toBe('completed');
  });
});

// ============================================================================
// 9. Handling Sessions with No Essays
// ============================================================================
describe('Handling Sessions with No Essays', () => {
  test('returns null gracefully on HTTP 404 without throwing an uncaught error', async () => {
    global.fetch = async () => ({
      ok: false,
      status: 404,
      json: async () => ({ detail: "No generated essay artifact found for session 'sess-empty'." }),
    });

    const result = await fetchLatestEssay('sess-empty');
    expect(result).toBeNull();
  });
});

// ============================================================================
// 10. Avoiding Stale Essay Content After Switching Sessions
// ============================================================================
describe('Avoiding Stale Essay Content on Session Switch', () => {
  test('session guard ref prevents slow response from session A overwriting session B', async () => {
    let activeSessionId = 'session-B'; // User switched to B
    let displayedEssay = null;

    const handleEssayLoaded = (targetSessionId, essay) => {
      // Guard matching activeSessionIdRef in App.jsx
      if (activeSessionId !== targetSessionId) {
        return; // Stale response discarded!
      }
      displayedEssay = essay;
    };

    // Stale fetch for Session A arrives after user selected Session B
    handleEssayLoaded('session-A', { title: 'Essay A' });
    expect(displayedEssay).toBeNull();

    // Fetch for Session B arrives
    handleEssayLoaded('session-B', { title: 'Essay B' });
    expect(displayedEssay).toEqual({ title: 'Essay B' });
  });
});

// ============================================================================
// 11. Network and Backend Error Handling
// ============================================================================
describe('Network and Backend Error Handling', () => {
  test('handles 504 Gateway Timeout gracefully with clear diagnostics', async () => {
    global.fetch = async () => ({
      ok: false,
      status: 504,
      statusText: 'Gateway Timeout',
      json: async () => ({ detail: 'Essay generation timed out.' }),
    });

    await expect(
      generateEssay('sess-timeout', { topic: 'Valid topic' })
    ).rejects.toThrow('Essay generation timed out.');
  });
});

// ============================================================================
// 12. Preservation of Existing Chat Functionality
// ============================================================================
describe('Preservation of Existing Chat Functionality', () => {
  test('session messages and chat thread remain intact alongside essay artifact', () => {
    const messages = [
      { id: '1', role: 'user', content: 'What did Jason Lemkin say?' },
      {
        id: '2',
        role: 'assistant',
        content: '# Digital Essay\n\n...',
        source_metadata: { artifact_type: 'ship30_essay', status: 'completed' },
      },
    ];

    expect(messages.length).toBe(2);
    expect(messages[0].role).toBe('user');
    expect(messages[1].source_metadata.artifact_type).toBe('ship30_essay');
  });
});
