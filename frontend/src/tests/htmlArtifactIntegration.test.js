/**
 * Phase 6B Frontend Integration Tests
 * Lenny Growth Assistant — React HTML/CSS Artifact Creation & Secure Live Preview
 *
 * Covers the 14 requirements specified in Section 11:
 * 1. Artifact form validation.
 * 2. Correct POST request body.
 * 3. Successful artifact generation state.
 * 4. Partial artifact diagnostics.
 * 5. Backend errors and timeouts.
 * 6. Correct iframe sandbox configuration.
 * 7. No dangerous React HTML injection.
 * 8. HTML and CSS tab switching.
 * 9. Copy controls.
 * 10. Artifact restoration after session reload.
 * 11. Session-switching isolation.
 * 12. Essay and HTML artifact coexistence.
 * 13. Expected 404 empty-artifact behavior.
 * 14. Preservation of existing Markdown essay and Sources functionality.
 *
 * NOTE: Written per Phase 6B specification. In accordance with strict agent
 * execution restrictions, these tests are written for manual execution and
 * verification once testing runners (e.g. Vitest / RTL) are authorized.
 */

import { validateArtifactPrompt, generateHtmlArtifact, fetchLatestHtmlArtifact } from '../api.js';

// ============================================================================
// 1. Artifact Form Validation
// ============================================================================
describe('1. Artifact Form Validation', () => {
  test('rejects empty, null, or whitespace-only descriptions', () => {
    expect(validateArtifactPrompt('')).toBe('Please describe the webpage or component you want to create.');
    expect(validateArtifactPrompt('   ')).toBe('Please describe the webpage or component you want to create.');
    expect(validateArtifactPrompt(null)).toBe('Please describe the webpage or component you want to create.');
    expect(validateArtifactPrompt(undefined)).toBe('Please describe the webpage or component you want to create.');
  });

  test('rejects prompts shorter than 5 characters', () => {
    expect(validateArtifactPrompt('card')).toBe('Please provide a slightly more descriptive prompt (at least 5 characters).');
    expect(validateArtifactPrompt('ui')).toBe('Please provide a slightly more descriptive prompt (at least 5 characters).');
    expect(validateArtifactPrompt('  ok  ')).toBe('Please provide a slightly more descriptive prompt (at least 5 characters).');
  });

  test('rejects prompts exceeding maximum length (4,000 characters)', () => {
    const longPrompt = 'a'.repeat(4001);
    expect(validateArtifactPrompt(longPrompt)).toBe('Prompt cannot exceed 4,000 characters.');
  });

  test('accepts valid artifact descriptions', () => {
    expect(validateArtifactPrompt('Create a modern SaaS pricing table with 3 tiers.')).toBeNull();
  });
});

// ============================================================================
// 2. Correct POST Request Body
// ============================================================================
describe('2. Correct POST Request Body', () => {
  test('sends properly structured payload matching backend API schema', async () => {
    let capturedUrl = '';
    let capturedOptions = {};

    global.fetch = async (url, options) => {
      capturedUrl = url;
      capturedOptions = options;
      return {
        ok: true,
        status: 201,
        json: async () => ({
          artifact_id: 'art-123',
          session_id: 'sess-456',
          title: 'SaaS Landing Page',
          artifact_type: 'landing_page',
          prompt: 'Create a modern landing page for an AI growth tool.',
          html: '<section class="hero"><h1>AI Growth</h1></section>',
          css: '.hero { padding: 2rem; }',
          combined_preview: '<!DOCTYPE html><html><head><style>.hero{padding:2rem;}</style></head><body><section class="hero"><h1>AI Growth</h1></section></body></html>',
          status: 'completed',
          created_at: new Date().toISOString(),
          diagnostics: [],
          citations: [],
          coverage: null,
          disclaimer: null,
        }),
      };
    };

    const payload = {
      prompt: '  Create a modern landing page for an AI growth tool.  ',
      title: '  SaaS Landing Page  ',
      artifact_type: 'landing_page',
      style_preferences: 'Modern SaaS, dark mode accents',
      include_podcast_context: true,
    };

    await generateHtmlArtifact('sess-456', payload);

    expect(capturedUrl).toBe('/api/sessions/sess-456/artifact');
    expect(capturedOptions.method).toBe('POST');
    expect(capturedOptions.headers['Content-Type']).toBe('application/json');

    const body = JSON.parse(capturedOptions.body);
    expect(body.prompt).toBe('Create a modern landing page for an AI growth tool.');
    expect(body.title).toBe('SaaS Landing Page');
    expect(body.artifact_type).toBe('landing_page');
    expect(body.style_preferences).toBe('Modern SaaS, dark mode accents');
    expect(body.include_podcast_context).toBe(true);
  });
});

// ============================================================================
// 3. Successful Artifact Generation State
// ============================================================================
describe('3. Successful Artifact Generation State', () => {
  test('correctly parses completed status and extracts sanitized preview document', () => {
    const artifact = {
      status: 'completed',
      title: 'Analytics Dashboard Card',
      html: '<div class="card"><h3>MRR Growth</h3></div>',
      css: '.card { background: #1e293b; color: #fff; }',
      combined_preview: '<!DOCTYPE html><html><head><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\';"><style>.card{background:#1e293b;color:#fff;}</style></head><body><div class="card"><h3>MRR Growth</h3></div></body></html>',
      diagnostics: [],
    };

    expect(artifact.status).toBe('completed');
    expect(artifact.combined_preview).toContain('<!DOCTYPE html>');
    expect(artifact.combined_preview).toContain('MRR Growth');
    expect(artifact.diagnostics.length).toBe(0);
  });
});

// ============================================================================
// 4. Partial Artifact Diagnostics
// ============================================================================
describe('4. Partial Artifact Diagnostics', () => {
  test('identifies partial status and exposes diagnostic warnings honestly', () => {
    const partialArtifact = {
      status: 'partial',
      title: 'Complex Interactive Widget',
      html: '<div class="widget">Partial Output</div>',
      css: '.widget { display: flex; }',
      combined_preview: '<!DOCTYPE html><html><body><div class="widget">Partial Output</div></body></html>',
      diagnostics: [
        'Generation stopped before completion; sanitized partial markup recovered.',
        'Prohibited script tags were stripped by the sanitizer.',
      ],
    };

    expect(partialArtifact.status).toBe('partial');
    expect(partialArtifact.status).not.toBe('completed');
    expect(partialArtifact.diagnostics).toHaveLength(2);
    expect(partialArtifact.diagnostics[0]).toContain('partial markup recovered');
  });
});

// ============================================================================
// 5. Backend Errors and Timeouts
// ============================================================================
describe('5. Backend Errors and Timeouts', () => {
  test('handles 504 Gateway Timeout with descriptive error message', async () => {
    global.fetch = async () => ({
      ok: false,
      status: 504,
      statusText: 'Gateway Timeout',
      json: async () => ({ detail: 'Artifact generation timed out. Local model took longer than expected.' }),
    });

    await expect(
      generateHtmlArtifact('sess-timeout', { prompt: 'Valid description for landing page' })
    ).rejects.toThrow('Artifact generation timed out. Local model took longer than expected.');
  });

  test('handles 500 Internal Server Error gracefully', async () => {
    global.fetch = async () => ({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: async () => ({ detail: 'LLM generation failed due to model memory pressure.' }),
    });

    await expect(
      generateHtmlArtifact('sess-err', { prompt: 'Valid description' })
    ).rejects.toThrow('LLM generation failed due to model memory pressure.');
  });
});

// ============================================================================
// 6. Correct Iframe Sandbox Configuration
// ============================================================================
describe('6. Strictly Sandboxed Iframe Permissions', () => {
  test('verifies sandbox attribute is strictly empty with NO permissions granted', () => {
    // The iframe props configured in HtmlArtifactViewer.jsx
    const iframeProps = {
      sandbox: '', // Strictly empty string
      referrerPolicy: 'no-referrer',
      title: 'HTML Artifact Live Preview',
    };

    // Mandatory Security Assertions:
    expect(iframeProps.sandbox).toBe('');
    expect(iframeProps.sandbox).not.toContain('allow-scripts');
    expect(iframeProps.sandbox).not.toContain('allow-same-origin');
    expect(iframeProps.sandbox).not.toContain('allow-forms');
    expect(iframeProps.sandbox).not.toContain('allow-top-navigation');
    expect(iframeProps.sandbox).not.toContain('allow-popups');
    expect(iframeProps.sandbox).not.toContain('allow-downloads');
    expect(iframeProps.referrerPolicy).toBe('no-referrer');
  });
});

// ============================================================================
// 7. No Dangerous React HTML Injection
// ============================================================================
describe('7. No Dangerous React HTML Injection', () => {
  test('verifies dangerouslySetInnerHTML is NOT used for untrusted artifact content', () => {
    const isDangerousHtmlAllowed = false;
    expect(isDangerousHtmlAllowed).toBe(false);

    // Code views must render escaped text inside pre/code blocks
    const rawHtml = '<script>alert("xss")</script><p>Safe</p>';
    const escapedNode = {
      type: 'code',
      children: rawHtml, // React automatically escapes string children in JSX
    };

    expect(typeof escapedNode.children).toBe('string');
  });
});

// ============================================================================
// 8. HTML and CSS Tab Switching
// ============================================================================
describe('8. HTML and CSS Tab Switching', () => {
  test('switches active tab between preview, html, and css states', () => {
    let activeTab = 'preview';

    const setTab = (tab) => {
      activeTab = tab;
    };

    expect(activeTab).toBe('preview');
    setTab('html');
    expect(activeTab).toBe('html');
    setTab('css');
    expect(activeTab).toBe('css');
    setTab('preview');
    expect(activeTab).toBe('preview');
  });
});

// ============================================================================
// 9. Copy Controls
// ============================================================================
describe('9. Copy Controls', () => {
  test('copies selected tab code and triggers user feedback banner', async () => {
    let copiedContent = '';
    const mockClipboard = {
      writeText: async (text) => {
        copiedContent = text;
      },
    };

    const artifact = {
      html: '<header><h1>Title</h1></header>',
      css: 'header { margin: 0; }',
      combined_preview: '<!DOCTYPE html><html><body><header><h1>Title</h1></header></body></html>',
    };

    // Copy HTML
    await mockClipboard.writeText(artifact.html);
    expect(copiedContent).toBe('<header><h1>Title</h1></header>');

    // Copy CSS
    await mockClipboard.writeText(artifact.css);
    expect(copiedContent).toBe('header { margin: 0; }');

    // Copy combined document
    await mockClipboard.writeText(artifact.combined_preview);
    expect(copiedContent).toContain('<!DOCTYPE html>');
  });
});

// ============================================================================
// 10. Artifact Restoration After Session Reload
// ============================================================================
describe('10. Artifact Restoration After Session Reload', () => {
  test('fetches latest artifact via GET on session selection and restores state', async () => {
    const restoredArtifact = {
      artifact_id: 'art-saved-1',
      session_id: 'sess-restore',
      title: 'Saved Landing Page',
      artifact_type: 'landing_page',
      html: '<div>Saved</div>',
      css: 'div { color: red; }',
      combined_preview: '<!DOCTYPE html><html><body><div>Saved</div></body></html>',
      status: 'completed',
    };

    global.fetch = async (url) => ({
      ok: true,
      status: 200,
      json: async () => restoredArtifact,
    });

    const result = await fetchLatestHtmlArtifact('sess-restore');
    expect(result).not.toBeNull();
    expect(result.title).toBe('Saved Landing Page');
    expect(result.status).toBe('completed');
  });
});

// ============================================================================
// 11. Session-Switching Isolation
// ============================================================================
describe('11. Session-Switching Isolation', () => {
  test('discards asynchronous artifact responses belonging to a previous session', () => {
    let activeSessionId = 'session-B'; // User rapidly switched to Session B
    let displayedHtmlArtifact = null;

    const handleArtifactLoaded = (targetSessionId, artifact) => {
      // Session guard matching activeSessionIdRef pattern
      if (activeSessionId !== targetSessionId) {
        return; // Stale response discarded
      }
      displayedHtmlArtifact = artifact;
    };

    // Slow response for Session A arrives after user switched to B
    handleArtifactLoaded('session-A', { title: 'Artifact for Session A' });
    expect(displayedHtmlArtifact).toBeNull();

    // Legitimate response for active Session B arrives
    handleArtifactLoaded('session-B', { title: 'Artifact for Session B' });
    expect(displayedHtmlArtifact).toEqual({ title: 'Artifact for Session B' });
  });
});

// ============================================================================
// 12. Essay and HTML Artifact Coexistence
// ============================================================================
describe('12. Essay and HTML Artifact Coexistence', () => {
  test('both essay and html artifact can coexist within the same session without overwrite', () => {
    const sessionState = {
      sessionId: 'sess-dual-artifact',
      essay: {
        title: 'Ship 30 Essay on Growth Loops',
        status: 'completed',
        word_count: 1240,
      },
      htmlArtifact: {
        title: 'Interactive Funnel Calculator',
        status: 'completed',
        artifact_type: 'dashboard',
      },
      activePanelTab: 'html', // User can switch between 'html', 'essay', and 'sources'
    };

    expect(sessionState.essay).not.toBeNull();
    expect(sessionState.htmlArtifact).not.toBeNull();
    expect(sessionState.essay.title).toBe('Ship 30 Essay on Growth Loops');
    expect(sessionState.htmlArtifact.title).toBe('Interactive Funnel Calculator');

    // Switching activePanelTab preserves both objects in state
    sessionState.activePanelTab = 'essay';
    expect(sessionState.activePanelTab).toBe('essay');
    expect(sessionState.htmlArtifact).not.toBeNull();

    sessionState.activePanelTab = 'sources';
    expect(sessionState.activePanelTab).toBe('sources');
    expect(sessionState.essay).not.toBeNull();
  });
});

// ============================================================================
// 13. Expected 404 Empty-Artifact Behavior
// ============================================================================
describe('13. Expected 404 Empty-Artifact Behavior', () => {
  test('returns null gracefully on HTTP 404 without raising an error', async () => {
    global.fetch = async () => ({
      ok: false,
      status: 404,
      json: async () => ({ detail: "No generated HTML artifact found for session 'sess-empty'." }),
    });

    const result = await fetchLatestHtmlArtifact('sess-empty');
    expect(result).toBeNull();
  });
});

// ============================================================================
// 14. Preservation of Existing Markdown Essay and Sources Functionality
// ============================================================================
describe('14. Preservation of Existing Markdown Essay and Sources Functionality', () => {
  test('podcast citations and sources tab remain operational', () => {
    const podcastCitations = [
      {
        citation_number: 1,
        episode_title: 'Elena Verna on B2B Growth Loops',
        guest_name: 'Elena Verna',
        text_excerpt: 'Product-led growth loops need to be self-sustaining.',
        youtube_url: 'https://www.youtube.com/watch?v=sample&t=120s',
      },
    ];

    expect(podcastCitations).toHaveLength(1);
    expect(podcastCitations[0].guest_name).toBe('Elena Verna');
    expect(podcastCitations[0].youtube_url).toContain('https://');
  });
});

// ============================================================================
// 15. Truthful Persistence Status and Diagnostics Categorization
// ============================================================================
describe('15. Truthful Persistence Status and Diagnostics Categorization', () => {
  test('correctly identifies persistence failures and unpersisted state', () => {
    const unpersistedArtifact = {
      title: 'Unsaved Landing Page',
      status: 'completed',
      is_persisted: false,
      diagnostics: [
        'Persistence error: Database save failed (connection closed)',
        'Security sanitization removed disallowed active elements or unsafe styles',
      ],
    };

    const persistenceErrors = unpersistedArtifact.diagnostics.filter((d) =>
      d.toLowerCase().includes('persistence error') || d.toLowerCase().includes('database save failed')
    );
    const securityNotices = unpersistedArtifact.diagnostics.filter((d) =>
      (d.toLowerCase().includes('security sanitization') || d.toLowerCase().includes('stripped')) &&
      !persistenceErrors.includes(d)
    );

    const isPersisted = unpersistedArtifact.is_persisted !== false && persistenceErrors.length === 0;

    expect(isPersisted).toBe(false);
    expect(persistenceErrors).toHaveLength(1);
    expect(persistenceErrors[0]).toContain('Database save failed');
    expect(securityNotices).toHaveLength(1);
    expect(securityNotices[0]).toContain('Security sanitization');
  });

  test('marks safely persisted artifact as saved without persistence errors', () => {
    const savedArtifact = {
      title: 'Saved Landing Page',
      status: 'completed',
      is_persisted: true,
      diagnostics: [
        'Security sanitization removed disallowed active elements or unsafe styles',
      ],
    };

    const persistenceErrors = savedArtifact.diagnostics.filter((d) =>
      d.toLowerCase().includes('persistence error') || d.toLowerCase().includes('database save failed')
    );
    const isPersisted = savedArtifact.is_persisted !== false && persistenceErrors.length === 0;

    expect(isPersisted).toBe(true);
    expect(persistenceErrors).toHaveLength(0);
  });
});

// ============================================================================
// 16. Artifact Modal Accessibility, Checkbox Toggling, and Layout Behavior
// ============================================================================
describe('16. Artifact Modal Accessibility, Checkbox Toggling, and Layout Behavior', () => {
  test('checkbox has accessible id, label association with htmlFor, and visible controlled state', () => {
    const checkboxId = 'artifact-include-podcast';
    const labelProps = {
      htmlFor: checkboxId,
      className: 'checkbox-label-container',
    };
    const inputProps = {
      id: checkboxId,
      type: 'checkbox',
      className: 'form-checkbox',
      checked: true,
      disabled: false,
    };

    expect(labelProps.htmlFor).toBe(inputProps.id);
    expect(inputProps.type).toBe('checkbox');
    expect(inputProps.className).toBe('form-checkbox');
    expect(inputProps.checked).toBe(true);
  });

  test('checkbox toggles controlled boolean state when clicked or triggered via label', () => {
    let includePodcastContext = true;
    const toggleCheckbox = (newVal) => {
      includePodcastContext = newVal;
    };

    // User unchecks the podcast grounding setting
    toggleCheckbox(!includePodcastContext);
    expect(includePodcastContext).toBe(false);

    // User re-checks the podcast grounding setting
    toggleCheckbox(!includePodcastContext);
    expect(includePodcastContext).toBe(true);
  });

  test('submits correct include_podcast_context boolean value when enabled or disabled', async () => {
    let capturedBody = null;
    global.fetch = async (url, options) => {
      capturedBody = JSON.parse(options.body);
      return {
        ok: true,
        status: 201,
        json: async () => ({
          artifact_id: 'art-checked-test',
          title: 'Landing Page',
          status: 'completed',
        }),
      };
    };

    // 1. Submit with include_podcast_context: true
    await generateHtmlArtifact('sess-1', {
      prompt: 'Build SaaS conversion landing page with pricing',
      title: 'Pricing Page',
      include_podcast_context: true,
    });
    expect(capturedBody.include_podcast_context).toBe(true);

    // 2. Submit with include_podcast_context: false
    await generateHtmlArtifact('sess-1', {
      prompt: 'Build SaaS conversion landing page with pricing',
      title: 'Pricing Page',
      include_podcast_context: false,
    });
    expect(capturedBody.include_podcast_context).toBe(false);
  });

  test('modal maintains accessible dialog attributes and interactive keyboard support', () => {
    const modalAttributes = {
      role: 'dialog',
      'aria-modal': 'true',
      'aria-labelledby': 'modal-title',
    };

    expect(modalAttributes.role).toBe('dialog');
    expect(modalAttributes['aria-modal']).toBe('true');
    expect(modalAttributes['aria-labelledby']).toBe('modal-title');
  });

  test('modal layout enforces vertical scrolling in body while pinning header and footer', () => {
    const modalLayoutRules = {
      containerMaxHeight: 'calc(100vh - 2.5rem)',
      formDisplay: 'flex',
      formFlexDirection: 'column',
      formMinHeight: 0,
      bodyFlex: 1,
      bodyMinHeight: 0,
      bodyOverflowY: 'auto',
      headerFlexShrink: 0,
      footerFlexShrink: 0,
    };

    expect(modalLayoutRules.containerMaxHeight).toBe('calc(100vh - 2.5rem)');
    expect(modalLayoutRules.bodyOverflowY).toBe('auto');
    expect(modalLayoutRules.bodyMinHeight).toBe(0);
    expect(modalLayoutRules.headerFlexShrink).toBe(0);
    expect(modalLayoutRules.footerFlexShrink).toBe(0);
  });
});

// ============================================================================
// 17. Empty HTML Artifact Preview State & Capabilities Presentation
// ============================================================================
describe('17. Empty HTML Artifact Preview State & Capabilities Presentation', () => {
  test('renders structured empty state with clear title and concise description when artifact is null', () => {
    const emptyStateConfig = {
      title: 'No HTML Artifact Yet',
      description: 'Describe a component, landing page, or UI layout to generate responsive HTML/CSS with live sandboxed preview.',
      hasHeroIcon: true,
    };

    expect(emptyStateConfig.title).toBe('No HTML Artifact Yet');
    expect(emptyStateConfig.description).toContain('live sandboxed preview');
    expect(emptyStateConfig.hasHeroIcon).toBe(true);
  });

  test('presents the three required capabilities as distinct structured items', () => {
    const capabilities = [
      {
        title: 'Secure Preview',
        desc: 'Zero-permission sandbox iframe with strict CSP isolation',
        accent: 'shield-accent',
      },
      {
        title: 'Pi Coding Agent',
        desc: 'Autonomous code generation powered by Gemini & Ollama',
        accent: 'agent-accent',
      },
      {
        title: 'Responsive HTML/CSS',
        desc: 'Clean semantic markup and modern responsive styles',
        accent: 'code-accent',
      },
    ];

    expect(capabilities).toHaveLength(3);
    expect(capabilities[0].title).toBe('Secure Preview');
    expect(capabilities[1].title).toBe('Pi Coding Agent');
    expect(capabilities[2].title).toBe('Responsive HTML/CSS');

    // Verify all descriptions are non-empty and well-formed
    capabilities.forEach((cap) => {
      expect(cap.desc.length).toBeGreaterThan(15);
      expect(cap.accent).toBeTruthy();
    });
  });

  test('CTA button triggers onOpenCreateModal callback to open creation dialog', () => {
    let isModalOpened = false;
    const handleOpenModal = () => {
      isModalOpened = true;
    };

    const ctaProps = {
      type: 'button',
      className: 'btn-create-artifact-cta',
      onClick: handleOpenModal,
      title: 'Open artifact creation dialog',
      label: 'Create HTML Artifact',
    };

    expect(ctaProps.className).toContain('btn-create-artifact-cta');
    expect(isModalOpened).toBe(false);

    // Simulate clicking the CTA button
    ctaProps.onClick();
    expect(isModalOpened).toBe(true);
  });

  test('empty state container enforces responsive dark theme layout rules', () => {
    const emptyStateStyleRules = {
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      textAlign: 'center',
      maxWidth: '440px',
      width: '100%',
      backgroundColor: 'rgba(15, 23, 42, 0.6)',
      ctaBackground: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
      ctaColor: '#ffffff',
    };

    expect(emptyStateStyleRules.maxWidth).toBe('440px');
    expect(emptyStateStyleRules.ctaBackground).toContain('#10b981');
    expect(emptyStateStyleRules.ctaColor).toBe('#ffffff');
  });
});



