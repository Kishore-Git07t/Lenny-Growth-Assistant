import React, { useState } from 'react';
import SafeMarkdown from './SafeMarkdown.jsx';
import { validateEssayTopic } from './api.js';

/**
 * EssayViewer Component
 *
 * Provides:
 * 1. Compact essay generation form with topic validation, optional audience, and fixed 1,250 target word count.
 * 2. Honest long-running generation loading state (Ollama local model takes several minutes).
 * 3. Rendered Markdown article viewer with safe external links and citation badges.
 * 4. Completed vs. Partial generation status distinctions with honesty about content thresholds.
 * 5. One-click Markdown copy to clipboard with real-time feedback.
 * 6. Structured podcast sources with verified YouTube timestamps.
 */
export default function EssayViewer({
  essay = null,
  isGenerating = false,
  generationError = null,
  onGenerateEssay,
  activeSessionId = null,
  onCreateSession = null,
  onViewSources = null,
}) {
  // Form input state
  const [showForm, setShowForm] = useState(false);
  const [topic, setTopic] = useState('');
  const [audience, setAudience] = useState('Early-stage SaaS founders');
  const [validationError, setValidationError] = useState('');
  
  // Clipboard copy state
  const [copied, setCopied] = useState(false);
  const [copyFeedback, setCopyFeedback] = useState('');

  // Handle Form Submission
  const handleSubmit = (e) => {
    e.preventDefault();
    setValidationError('');

    const topicError = validateEssayTopic(topic);
    if (topicError) {
      setValidationError(topicError);
      return;
    }

    if (!activeSessionId) {
      setValidationError('Please select or create a conversation session first.');
      return;
    }

    onGenerateEssay({
      topic: topic.trim(),
      audience: audience.trim() || null,
      target_word_count: 1250,
    });
    setShowForm(false);
  };

  // Copy Markdown to Clipboard
  // Copy Markdown to Clipboard
  const handleCopyMarkdown = async () => {
    if (!essay?.content) return;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(essay.content);
      } else {
        // Fallback for browsers or contexts without Async Clipboard API
        const textArea = document.createElement('textarea');
        textArea.value = essay.content;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        textArea.style.top = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        const successful = document.execCommand('copy');
        document.body.removeChild(textArea);
        if (!successful) throw new Error('Fallback copy failed');
      }
      setCopied(true);
      setCopyFeedback('Markdown copied to clipboard!');
      setTimeout(() => {
        setCopied(false);
        setCopyFeedback('');
      }, 2500);
    } catch {
      setCopyFeedback('Copy failed. Please select and copy text manually.');
      setTimeout(() => setCopyFeedback(''), 3000);
    }
  };

  // 1. Long-Running Generation State
  if (isGenerating) {
    return (
      <div className="essay-viewer-card" aria-live="polite">
        <div className="essay-generating-state">
          <div className="generating-spinner-container">
            <div className="generating-pulse-ring"></div>
            <div className="generating-core-icon">📝</div>
          </div>
          <h3 className="generating-title">Generating your essay...</h3>
          <p className="generating-description">
            Pi Coding Agent is synthesizing podcast transcripts, producing a structured outline,
            and drafting 5 grounded sections using your local Ollama model.
          </p>
          <div className="generating-notice-box">
            <div className="notice-icon">⏱️</div>
            <div className="notice-content">
              <strong>Local Inference Note:</strong>
              <p>
                Generating a ~1,250-word grounded essay takes several minutes on local models.
                Please keep this window open while generation completes.
              </p>
            </div>
          </div>
          <div className="generating-specs">
            <span className="spec-badge">Word Target: 1,250 words</span>
            <span className="spec-badge">Framework: Ship 30 for 30</span>
            <span className="spec-badge">Evidence: Verified Transcripts</span>
          </div>
        </div>
      </div>
    );
  }

  // 2. Essay Generation Form Mode (Shown when explicitly requested or when no essay exists)
  if (showForm || !essay) {
    return (
      <div className="essay-viewer-card">
        <div className="essay-form-header">
          <div className="essay-form-title-group">
            <span className="form-icon">✍️</span>
            <div>
              <h3 className="essay-form-title">Generate Ship 30 for 30 Essay</h3>
              <p className="essay-form-subtitle">
                Synthesize podcast insights into a structured, publication-ready digital essay.
              </p>
            </div>
          </div>
          {essay && (
            <button
              type="button"
              className="btn-cancel-form"
              onClick={() => setShowForm(false)}
            >
              Back to Essay
            </button>
          )}
        </div>

        {generationError && (
          <div className="essay-error-banner" role="alert">
            <span className="error-icon">⚠️</span>
            <span className="error-msg">{generationError}</span>
          </div>
        )}

        {!activeSessionId && (
          <div className="no-session-guidance">
            <p>No active conversation session is selected.</p>
            {onCreateSession && (
              <button
                type="button"
                className="btn-guidance-create"
                onClick={onCreateSession}
              >
                + Start New Session
              </button>
            )}
          </div>
        )}

        <form className="essay-generator-form" onSubmit={handleSubmit}>
          {/* Topic Input */}
          <div className="form-group">
            <label htmlFor="essay-topic-input" className="form-label">
              Topic or Question <span className="required-star">*</span>
            </label>
            <textarea
              id="essay-topic-input"
              className="essay-input essay-textarea"
              rows={3}
              placeholder="e.g. What can early-stage SaaS founders learn about AI sales agents from Jason Lemkin?"
              value={topic}
              onChange={(e) => {
                setTopic(e.target.value);
                if (validationError) setValidationError('');
              }}
              disabled={isGenerating || !activeSessionId}
            />
            <span className="form-hint">
              Be specific about the topic, framework or guest lessons to retrieve.
            </span>
          </div>

          {/* Target Audience Input */}
          <div className="form-group">
            <label htmlFor="essay-audience-input" className="form-label">
              Target Audience <span className="optional-tag">(Optional)</span>
            </label>
            <input
              id="essay-audience-input"
              type="text"
              className="essay-input"
              placeholder="e.g. Early-stage SaaS founders"
              value={audience}
              onChange={(e) => setAudience(e.target.value)}
              disabled={isGenerating || !activeSessionId}
            />
            <span className="form-hint">
              Shapes tone, examples, and the core hook to match your reader persona.
            </span>
          </div>

          {/* Target Word Count (Fixed per Ship 30 Standard) */}
          <div className="form-group">
            <label className="form-label">Target Word Count</label>
            <div className="fixed-word-count-badge">
              <span className="fixed-count-value">1,250 words</span>
              <span className="fixed-count-desc">
                Standard Ship 30 essay target (1,100–1,400 accepted range)
              </span>
            </div>
          </div>

          {validationError && (
            <div className="form-validation-error">{validationError}</div>
          )}

          {/* Submit Action */}
          <div className="form-actions">
            <button
              type="submit"
              className="btn-generate-submit"
              disabled={isGenerating || !activeSessionId || !topic.trim()}
            >
              <span>🚀</span> Generate Essay
            </button>
          </div>
        </form>
      </div>
    );
  }

  // 3. Rendered Essay Article View
  const isCompleted = essay.status === 'completed';
  const isPartial = essay.status === 'partial';
  const isInsufficient = essay.status === 'insufficient_evidence';
  const citations = Array.isArray(essay.citations) ? essay.citations : [];
  const hasSourcesInMarkdown = /(?:^|\n)#{1,4}\s+Sources\b/i.test(essay.content || '');

  const statusPillClass = isCompleted
    ? 'status-pill-completed'
    : isPartial || isInsufficient
    ? 'status-pill-partial'
    : 'status-pill-info';

  const statusPillLabel = isCompleted
    ? '✓ Completed'
    : isPartial
    ? '⚠️ Partial Result'
    : isInsufficient
    ? '⚠️ Insufficient Evidence'
    : essay.status;

  return (
    <article className="essay-viewer-card" aria-label="Generated Essay Article">
      {/* Top Action & Navigation Bar */}
      <div className="essay-toolbar">
        <div className="toolbar-left">
          <span className={`status-pill ${statusPillClass}`}>
            {statusPillLabel}
          </span>
          <span className="word-count-pill">
            <strong>{essay.word_count?.toLocaleString()}</strong> / {essay.target_word_count || 1250} words
          </span>
        </div>

        <div className="toolbar-right">
          <button
            type="button"
            className="btn-toolbar-action btn-copy-markdown"
            onClick={handleCopyMarkdown}
            title="Copy raw Markdown to clipboard"
          >
            {copied ? '✓ Copied!' : '📋 Copy Markdown'}
          </button>
          <button
            type="button"
            className="btn-toolbar-action btn-new-essay"
            onClick={() => setShowForm(true)}
            title="Generate a new essay for this session"
          >
            ✍️ New Essay
          </button>
        </div>
      </div>

      {copyFeedback && (
        <div className="copy-feedback-toast" role="status">
          {copyFeedback}
        </div>
      )}

      {/* Partial Generation Honest Advisory */}
      {isPartial && (
        <div className="partial-warning-card" role="alert">
          <div className="partial-warning-header">
            <span>⚠️</span>
            <strong>Editorial Review Recommended</strong>
          </div>
          <p className="partial-warning-text">
            This essay was generated as a <strong>partial</strong> result by the backend validator.
            The word count ({essay.word_count} words) may fall outside the target 1,100–1,400 word
            envelope, or sections may require additional evidence reconciliation.
          </p>
        </div>
      )}

      {/* Partial Corpus Index Disclaimer */}
      {essay.disclaimer && (
        <div className="partial-index-callout">
          <div className="disclaimer-title">⚠️ Corpus Coverage Notice</div>
          <p className="disclaimer-text">{essay.disclaimer}</p>
        </div>
      )}

      {/* Essay Metadata Bar */}
      <div className="essay-meta-strip">
        <div className="meta-strip-item">
          <span className="strip-label">Audience:</span>
          <span className="strip-value">{essay.audience || 'Product leaders'}</span>
        </div>
        <div className="meta-strip-item">
          <span className="strip-label">Model:</span>
          <span className="strip-value">
            {essay.model || 'qwen2.5:1.5b'} ({essay.provider || 'ollama'})
          </span>
        </div>
        {essay.created_at && (
          <div className="meta-strip-item">
            <span className="strip-label">Generated:</span>
            <span className="strip-value">
              {new Date(essay.created_at).toLocaleDateString([], {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              })}
            </span>
          </div>
        )}
      </div>

      {/* Rendered Essay Body */}
      <div className="essay-article-content">
        <SafeMarkdown content={essay.content} />
      </div>

      {/* Grounded Source Citations */}
      {citations.length > 0 && (
        hasSourcesInMarkdown ? (
          /* Streamlined Evidence Banner linking to the dedicated Sources tab to prevent duplicate lists */
          <section className="essay-evidence-summary-banner" aria-label="Podcast Source Evidence">
            <div className="evidence-summary-content">
              <span className="evidence-icon">🎧</span>
              <div className="evidence-text-group">
                <strong className="evidence-summary-title">
                  {citations.length} Grounded Podcast {citations.length === 1 ? 'Source' : 'Sources'}
                </strong>
                <span className="evidence-summary-desc">
                  Verbatim transcript passages and match scores can be inspected in the Sources tab.
                </span>
              </div>
            </div>
            {onViewSources && (
              <button
                type="button"
                className="btn-inspect-sources-tab"
                onClick={onViewSources}
                title="Open full transcript excerpts in the Sources tab"
              >
                Inspect Sources Tab →
              </button>
            )}
          </section>
        ) : (
          /* Fallback citation card list for historical essays without a terminal Sources section */
          <section className="essay-sources-section" aria-label="Podcast Source Evidence">
            <h3 className="sources-heading">
              <span>🎙️</span> Grounded Podcast Sources ({citations.length})
            </h3>
            <div className="citations-list">
              {citations.map((cite, index) => {
                const citeNum = index + 1;
                const linkUrl = cite.timestamped_url || cite.youtube_url;
                const simPercent =
                  typeof cite.similarity_score === 'number'
                    ? (cite.similarity_score * 100).toFixed(0)
                    : null;

                return (
                  <div key={cite.chunk_id || index} className="citation-card">
                    <div className="citation-card-header">
                      <span className="citation-number-badge">[{citeNum}]</span>
                      <div className="citation-titles">
                        <h4 className="citation-ep-title" title={cite.episode_title}>
                          {cite.episode_title}
                        </h4>
                        {cite.guest_name && (
                          <span className="citation-guest">Guest: {cite.guest_name}</span>
                        )}
                      </div>
                    </div>

                    <div className="citation-meta-row">
                      {cite.timestamp_label && (
                        <span className="citation-timestamp-pill">
                          ⏱️ {cite.timestamp_label}
                        </span>
                      )}
                      {simPercent && (
                        <span className="citation-sim-pill">
                          {simPercent}% similarity
                        </span>
                      )}
                    </div>

                    {cite.content && (
                      <blockquote className="citation-excerpt">
                        "{cite.content}"
                      </blockquote>
                    )}

                    {linkUrl && (
                      <div className="citation-link-wrapper">
                        <a
                          href={linkUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="btn-youtube-link"
                        >
                          <span>▶</span> Watch on YouTube{' '}
                          {cite.timestamp_label ? `at ${cite.timestamp_label}` : ''} ↗
                        </a>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        )
      )}
    </article>
  );
}
