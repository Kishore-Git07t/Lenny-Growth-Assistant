import React, { useState } from 'react';

/**
 * HtmlArtifactViewer Component
 *
 * Provides:
 * 1. Strict sandbox="" iframe rendering for live preview of backend-sanitized HTML/CSS documents.
 * 2. Escaped HTML and CSS source code viewers with syntax formatting.
 * 3. Copy controls for HTML, CSS, and full document with real-time feedback.
 * 4. Completed vs. Partial status indicators and backend diagnostics display.
 * 5. Direct links to associated podcast citations in the Sources tab.
 */
export default function HtmlArtifactViewer({
  artifact = null,
  isGenerating = false,
  generationError = null,
  onOpenCreateModal = null,
  onViewSources = null,
  activeSessionId = null,
}) {
  const [activeCodeTab, setActiveCodeTab] = useState('preview'); // 'preview' | 'html' | 'css'
  const [copyFeedback, setCopyFeedback] = useState('');
  const [copiedKey, setCopiedKey] = useState(null);

  // Copy helper with async clipboard API and textarea fallback
  const handleCopyText = async (text, key, label) => {
    if (!text) return;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        textArea.style.top = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        const successful = document.execCommand('copy');
        document.body.removeChild(textArea);
        if (!successful) throw new Error('Clipboard copy command was unsuccessful');
      }

      setCopiedKey(key);
      setCopyFeedback(`${label} copied to clipboard!`);
      setTimeout(() => {
        setCopiedKey(null);
        setCopyFeedback('');
      }, 2500);
    } catch {
      setCopyFeedback('Failed to copy. Please select and copy code manually.');
      setTimeout(() => setCopyFeedback(''), 3000);
    }
  };

  // 1. Long-Running Generation State
  if (isGenerating) {
    return (
      <div className="artifact-viewer-container" aria-live="polite">
        <div className="artifact-generating-state">
          <div className="generating-spinner-container">
            <div className="generating-pulse-ring"></div>
            <div className="generating-core-icon">🎨</div>
          </div>
          <h3 className="generating-title">Generating HTML/CSS Artifact</h3>
          <p className="generating-stage-desc">
            Invoking Pi Coding Agent subprocess to synthesize layout, responsive styling, and
            domain-specific copy...
          </p>
          <div className="generating-timeline">
            <div className="timeline-step done">✓ Analyzing prompt & design aesthetic</div>
            <div className="timeline-step done">✓ Querying podcast transcripts (pgvector)</div>
            <div className="timeline-step active">
              <span className="step-spin">⏳</span> Subprocess generating HTML & CSS rules...
            </div>
            <div className="timeline-step pending">○ Server-side security sanitization</div>
            <div className="timeline-step pending">○ Strict CSP sandboxed preview assembly</div>
          </div>
          <p className="generating-footnote">
            Local generation typically takes 1–3 minutes on standard hardware.
          </p>
        </div>
      </div>
    );
  }

  // 2. Generation Error State
  if (generationError && !artifact) {
    return (
      <div className="artifact-viewer-container">
        <div className="artifact-error-card" role="alert">
          <div className="error-card-header">
            <span className="error-icon">⚠️</span>
            <h3>Artifact Generation Error</h3>
          </div>
          <p className="error-card-message">{generationError}</p>
          <div className="error-card-actions">
            {onOpenCreateModal && (
              <button
                type="button"
                className="btn-retry-artifact"
                onClick={onOpenCreateModal}
              >
                Try Again
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // 3. Empty State (No Artifact Generated Yet for this Session)
  if (!artifact) {
    return (
      <div className="artifact-viewer-container">
        <div className="artifact-empty-hero">
          <div className="empty-hero-icon-container" aria-hidden="true">
            <svg
              className="empty-hero-svg"
              width="28"
              height="28"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect width="18" height="18" x="3" y="3" rx="2" />
              <path d="M3 9h18" />
              <path d="M9 21V9" />
            </svg>
          </div>

          <h3 className="empty-hero-title">No HTML Artifact Yet</h3>
          <p className="empty-hero-description">
            Describe a component, landing page, or UI layout to generate responsive HTML/CSS with live sandboxed preview.
          </p>

          <div className="empty-capabilities-list" role="list" aria-label="Artifact capabilities">
            <div className="capability-item" role="listitem">
              <div className="capability-icon-wrap shield-accent" aria-hidden="true">
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />
                  <path d="m9 12 2 2 4-4" />
                </svg>
              </div>
              <div className="capability-text">
                <span className="capability-title">Secure Preview</span>
                <span className="capability-desc">Zero-permission sandbox iframe with strict CSP isolation</span>
              </div>
            </div>

            <div className="capability-item" role="listitem">
              <div className="capability-icon-wrap agent-accent" aria-hidden="true">
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
                  <path d="M5 3v4" />
                  <path d="M19 17v4" />
                  <path d="M3 5h4" />
                  <path d="M17 19h4" />
                </svg>
              </div>
              <div className="capability-text">
                <span className="capability-title">Pi Coding Agent</span>
                <span className="capability-desc">Autonomous code generation powered by Gemini & Ollama</span>
              </div>
            </div>

            <div className="capability-item" role="listitem">
              <div className="capability-icon-wrap code-accent" aria-hidden="true">
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="m16 18 6-6-6-6" />
                  <path d="m8 6-6 6 6 6" />
                </svg>
              </div>
              <div className="capability-text">
                <span className="capability-title">Responsive HTML/CSS</span>
                <span className="capability-desc">Clean semantic markup and modern responsive styles</span>
              </div>
            </div>
          </div>

          {onOpenCreateModal && (
            <button
              type="button"
              className="btn-create-artifact-cta"
              onClick={onOpenCreateModal}
              title="Open artifact creation dialog"
            >
              <span className="btn-cta-icon" aria-hidden="true">+</span>
              <span>Create HTML Artifact</span>
            </button>
          )}
        </div>
      </div>
    );
  }

  // 4. Render Active Artifact (Preview, HTML, CSS)
  const isPartial = artifact.status === 'partial';
  const hasCitations = Array.isArray(artifact.citations) && artifact.citations.length > 0;

  // Extract and categorize diagnostics (deduplicating entries)
  const rawDiagnostics = Array.isArray(artifact.diagnostics) ? artifact.diagnostics : [];
  const uniqueDiagnostics = Array.from(new Set(rawDiagnostics.filter(Boolean)));

  const persistenceErrors = uniqueDiagnostics.filter((d) =>
    d.toLowerCase().includes('persistence error') ||
    d.toLowerCase().includes('database save failed')
  );
  const securityNotices = uniqueDiagnostics.filter((d) =>
    (d.toLowerCase().includes('security sanitization') ||
     d.toLowerCase().includes('stripped') ||
     d.toLowerCase().includes('disallowed') ||
     d.toLowerCase().includes('unsafe')) &&
    !persistenceErrors.includes(d)
  );
  const modelAdvisories = uniqueDiagnostics.filter(
    (d) => !persistenceErrors.includes(d) && !securityNotices.includes(d)
  );

  const isPersisted = artifact.is_persisted !== false && persistenceErrors.length === 0;
  const displayType = (artifact.artifact_type || 'landing_page').replace(/_/g, ' ');

  return (
    <div className="artifact-viewer-container">
      {/* Artifact Header Info */}
      <div className="artifact-view-header">
        <div className="artifact-view-titles">
          <div className="artifact-badge-row">
            <span className="artifact-type-badge">🎨 {displayType}</span>
            <span
              className={`artifact-status-badge ${
                isPartial ? 'status-badge-partial' : 'status-badge-completed'
              }`}
            >
              {isPartial ? '⚠️ Partial' : '✓ Completed'}
            </span>
            <span
              className={`artifact-persistence-badge ${
                isPersisted ? 'badge-persisted-saved' : 'badge-persisted-unsaved'
              }`}
              title={
                isPersisted
                  ? 'Persisted securely to PostgreSQL'
                  : 'In-memory only (Database persistence failed)'
              }
            >
              {isPersisted ? '💾 Saved' : '⚠️ Unsaved'}
            </span>
            {artifact.created_at && (
              <span className="artifact-date-tag">
                ⏱️ {new Date(artifact.created_at).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit',
                })}
              </span>
            )}
          </div>
          <h3 className="artifact-headline" title={artifact.title}>
            {artifact.title || 'Generated HTML/CSS Artifact'}
          </h3>
        </div>

        {/* View Mode Tabs: Preview / HTML / CSS */}
        <div className="artifact-view-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={activeCodeTab === 'preview'}
            className={`view-tab-btn ${activeCodeTab === 'preview' ? 'active' : ''}`}
            onClick={() => setActiveCodeTab('preview')}
            title="Interactive Live Sandbox Preview"
          >
            <span>👁️</span> Preview
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeCodeTab === 'html'}
            className={`view-tab-btn ${activeCodeTab === 'html' ? 'active' : ''}`}
            onClick={() => setActiveCodeTab('html')}
            title="Inspect HTML Source Code"
          >
            <span>📄</span> HTML
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeCodeTab === 'css'}
            className={`view-tab-btn ${activeCodeTab === 'css' ? 'active' : ''}`}
            onClick={() => setActiveCodeTab('css')}
            title="Inspect CSS Stylesheet"
          >
            <span>🎨</span> CSS
          </button>
        </div>
      </div>

      {/* Copy Toolbar & Actions */}
      <div className="artifact-toolbar">
        <div className="toolbar-copy-buttons">
          <button
            type="button"
            className={`btn-toolbar-action btn-copy-html ${copiedKey === 'html' ? 'copied' : ''}`}
            onClick={() => handleCopyText(artifact.html, 'html', 'HTML')}
            disabled={!artifact.html}
            title="Copy HTML to clipboard"
          >
            <span className="btn-icon">{copiedKey === 'html' ? '✓' : '📋'}</span>
            <span>{copiedKey === 'html' ? 'Copied HTML' : 'Copy HTML'}</span>
          </button>
          <button
            type="button"
            className={`btn-toolbar-action btn-copy-css ${copiedKey === 'css' ? 'copied' : ''}`}
            onClick={() => handleCopyText(artifact.css, 'css', 'CSS')}
            disabled={!artifact.css}
            title="Copy CSS to clipboard"
          >
            <span className="btn-icon">{copiedKey === 'css' ? '✓' : '🎨'}</span>
            <span>{copiedKey === 'css' ? 'Copied CSS' : 'Copy CSS'}</span>
          </button>
          <button
            type="button"
            className={`btn-toolbar-action btn-copy-doc ${copiedKey === 'all' ? 'copied' : ''}`}
            onClick={() =>
              handleCopyText(artifact.combined_preview, 'all', 'Full Document')
            }
            disabled={!artifact.combined_preview}
            title="Copy self-contained preview document"
          >
            <span className="btn-icon">{copiedKey === 'all' ? '✓' : '📄'}</span>
            <span>{copiedKey === 'all' ? 'Copied All' : 'Copy Document'}</span>
          </button>
        </div>

        {onOpenCreateModal && (
          <button
            type="button"
            className="btn-toolbar-action btn-toolbar-new"
            onClick={onOpenCreateModal}
            title="Generate a new HTML/CSS artifact"
          >
            <span className="btn-icon">+</span>
            <span>New Artifact</span>
          </button>
        )}
      </div>

      {copyFeedback && (
        <div className="copy-feedback-banner" role="status">
          <span>✓</span> {copyFeedback}
        </div>
      )}

      {/* Critical Database Persistence Failure Alert */}
      {persistenceErrors.length > 0 && (
        <div className="artifact-diag-persistence-card" role="alert">
          <div className="diag-alert-header">
            <span className="diag-alert-icon">⚠️</span>
            <span className="diag-alert-title">Database Persistence Error</span>
          </div>
          <p className="diag-alert-desc">
            The artifact is visible in this session preview, but could not be saved to PostgreSQL.
          </p>
          <ul className="diag-alert-list">
            {persistenceErrors.map((err, idx) => (
              <li key={idx}><code>{err}</code></li>
            ))}
          </ul>
        </div>
      )}

      {/* Security Sanitization & Layout Diagnostics */}
      {(isPartial || securityNotices.length > 0 || modelAdvisories.length > 0) && (
        <div className="artifact-diagnostics-card">
          <div className="diagnostics-title">
            <span>🛡️</span> Security & Layout Diagnostics
          </div>
          {isPartial && (
            <p className="diagnostics-summary">
              Model output was augmented with structured layout components to ensure valid, responsive rendering.
            </p>
          )}
          <ul className="diagnostics-list">
            {securityNotices.map((diag, idx) => (
              <li key={`sec-${idx}`} className="diag-item diag-item-security">
                <span className="diag-pill sec-pill">Sanitization</span>
                <span>{diag}</span>
              </li>
            ))}
            {modelAdvisories.map((diag, idx) => (
              <li key={`adv-${idx}`} className="diag-item diag-item-advisory">
                <span className="diag-pill adv-pill">Notice</span>
                <span>{diag}</span>
              </li>
            ))}
          </ul>
        </div>
      )}


      {/* Main Content Area */}
      <div className="artifact-display-viewport">
        {activeCodeTab === 'preview' && (
          <div className="iframe-sandbox-wrapper">
            {artifact.combined_preview ? (
              /*
               * MANDATORY SECURITY BOUNDARY:
               * sandbox="" enforces an empty permission set (no scripts, no same-origin,
               * no forms, no top-navigation, no popups, no downloads).
               * referrerPolicy="no-referrer" prevents header leaks.
               */
              <iframe
                srcDoc={artifact.combined_preview}
                sandbox=""
                title={artifact.title || 'HTML/CSS Artifact Live Preview'}
                referrerPolicy="no-referrer"
                className="html-artifact-iframe"
                loading="lazy"
              />
            ) : (
              <div className="iframe-missing-preview-card">
                <p>⚠️ Preview document was not provided by the backend.</p>
              </div>
            )}
          </div>
        )}

        {activeCodeTab === 'html' && (
          <div className="code-viewer-container">
            <div className="code-viewer-header">
              <span className="code-lang-label">HTML5 Source</span>
              <span className="code-chars-label">
                {artifact.html ? `${artifact.html.length.toLocaleString()} characters` : '0 characters'}
              </span>
            </div>
            <pre className="code-viewer-pre">
              <code className="code-viewer-code">{artifact.html || '<!-- No HTML generated -->'}</code>
            </pre>
          </div>
        )}

        {activeCodeTab === 'css' && (
          <div className="code-viewer-container">
            <div className="code-viewer-header">
              <span className="code-lang-label">CSS Stylesheet</span>
              <span className="code-chars-label">
                {artifact.css ? `${artifact.css.length.toLocaleString()} characters` : '0 characters'}
              </span>
            </div>
            <pre className="code-viewer-pre">
              <code className="code-viewer-code">{artifact.css || '/* No CSS generated */'}</code>
            </pre>
          </div>
        )}
      </div>

      {/* Podcast Sources Footer Link */}
      {hasCitations && onViewSources && (
        <div className="artifact-sources-footer">
          <button
            type="button"
            className="btn-artifact-sources-link"
            onClick={onViewSources}
            title="Inspect grounded transcript citations in Sources tab"
          >
            <span>📚</span> View {artifact.citations.length} Grounded Podcast Sources →
          </button>
        </div>
      )}
    </div>
  );
}
