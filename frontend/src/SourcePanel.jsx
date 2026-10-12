import React, { useState } from 'react';
import EssayViewer from './EssayViewer.jsx';
import HtmlArtifactViewer from './HtmlArtifactViewer.jsx';
import Icon from './Icon.jsx';

/**
 * Right panel component displaying:
 * 1. HTML/CSS Design Artifact Viewer with secure sandbox="" iframe (Phase 6B).
 * 2. Ship 30 for 30 Essay Artifact Viewer (Phase 5B).
 * 3. Retrieved podcast source citations with clickable YouTube timestamps.
 * 4. Model & retrieval status metadata and partial-index coverage advisory.
 */
export default function SourcePanel({
  citations = [],
  coverage = null,
  disclaimer = null,
  retrievalStatus = null,
  model = 'qwen2.5:1.5b',
  provider = 'ollama',
  essay = null,
  isGeneratingEssay = false,
  essayError = null,
  onGenerateEssay,
  htmlArtifact = null,
  isGeneratingHtml = false,
  htmlArtifactError = null,
  onOpenHtmlModal = null,
  activeSessionId = null,
  onCreateSession = null,
  activeTab = null,
  onTabChange = null,
  width = null,
}) {
  const [internalTab, setInternalTab] = useState('html');
  const currentTab = activeTab !== null && activeTab !== undefined ? activeTab : internalTab;

  const handleTabSwitch = (tab) => {
    if (onTabChange) {
      onTabChange(tab);
    } else {
      setInternalTab(tab);
    }
  };

  const hasCitations = Array.isArray(citations) && citations.length > 0;
  const hasEssay = Boolean(essay);
  const hasHtmlArtifact = Boolean(htmlArtifact);

  return (
    <aside
      className="artifact-sidebar"
      style={width ? { width: `${width}px` } : undefined}
      aria-label="Sources and Artifact Viewer"
    >
      {/* Panel Tab Navigation Header */}
      <div className="artifact-panel-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={currentTab === 'html'}
          className={`panel-tab-btn ${currentTab === 'html' ? 'active' : ''}`}
          onClick={() => handleTabSwitch('html')}
          title="HTML/CSS Design Artifact Live Preview"
        >
          <Icon name="layout" size={14} /> <span>HTML Artifact</span>
          {hasHtmlArtifact && <span className="tab-indicator-dot"></span>}
          {isGeneratingHtml && <span className="tab-spinner-mini"></span>}
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={currentTab === 'essay'}
          className={`panel-tab-btn ${currentTab === 'essay' ? 'active' : ''}`}
          onClick={() => handleTabSwitch('essay')}
          title="Ship 30 for 30 Digital Essay"
        >
          <Icon name="pen" size={14} /> <span>Essay Artifact</span>
          {hasEssay && <span className="tab-indicator-dot"></span>}
          {isGeneratingEssay && <span className="tab-spinner-mini"></span>}
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={currentTab === 'sources'}
          className={`panel-tab-btn ${currentTab === 'sources' ? 'active' : ''}`}
          onClick={() => handleTabSwitch('sources')}
          title="Retrieved Podcast Citations & Coverage"
        >
          <Icon name="book-open" size={14} /> <span>Sources</span>
          <span className="tab-count-badge">{hasCitations ? citations.length : 0}</span>
        </button>
      </div>

      <div className="artifact-scrollable-content">
        {currentTab === 'html' ? (
          /* HTML/CSS Artifact Viewer Tab */
          <HtmlArtifactViewer
            artifact={htmlArtifact}
            isGenerating={isGeneratingHtml}
            generationError={htmlArtifactError}
            onOpenCreateModal={onOpenHtmlModal}
            onViewSources={() => handleTabSwitch('sources')}
            activeSessionId={activeSessionId}
          />
        ) : currentTab === 'essay' ? (
          /* Essay Viewer / Generator Tab */
          <EssayViewer
            essay={essay}
            isGenerating={isGeneratingEssay}
            generationError={essayError}
            onGenerateEssay={onGenerateEssay}
            activeSessionId={activeSessionId}
            onCreateSession={onCreateSession}
            onViewSources={() => handleTabSwitch('sources')}
          />
        ) : (
          /* Retrieved Sources Tab */
          <>
            {/* Model & Agent Runtime Status */}
            <section className="source-section">
              <div className="source-section-title">AI Engine & Retrieval Status</div>
              <div className="runtime-meta-grid">
                <div className="meta-pill">
                  <span className="meta-label">Model:</span>
                  <span className="meta-value">{model}</span>
                </div>
                <div className="meta-pill">
                  <span className="meta-label">Runtime:</span>
                  <span className="meta-value">Pi Coding Agent ({provider})</span>
                </div>
                {retrievalStatus && (
                  <div className="meta-pill">
                    <span className="meta-label">Retrieval:</span>
                    <span
                      className={`meta-value ${
                        retrievalStatus === 'success'
                          ? 'status-success'
                          : 'status-warning'
                      }`}
                    >
                      {retrievalStatus === 'success'
                        ? 'Success'
                        : retrievalStatus === 'insufficient_evidence'
                        ? 'Insufficient Evidence'
                        : retrievalStatus}
                    </span>
                  </div>
                )}
              </div>
            </section>

            {/* Index Coverage & Partial Index Advisory */}
            {(coverage || disclaimer) && (
              <section className="source-section">
                <div className="source-section-title">Corpus Index Coverage</div>
                {coverage && (
                  <div className="coverage-card">
                    <div className="coverage-stat-row">
                      <span className="coverage-stat-label">Episodes Indexed:</span>
                      <span className="coverage-stat-val">
                        {coverage.indexed_episodes} / {coverage.total_episodes}
                      </span>
                    </div>
                    <div className="coverage-stat-row">
                      <span className="coverage-stat-label">Chunks Indexed:</span>
                      <span className="coverage-stat-val">
                        {coverage.indexed_chunks?.toLocaleString()} / {coverage.total_chunks?.toLocaleString()}
                      </span>
                    </div>
                    <div className="coverage-stat-row">
                      <span className="coverage-stat-label">Embedding Model:</span>
                      <span className="coverage-stat-val">{coverage.model_name || 'nomic-embed-text'}</span>
                    </div>
                  </div>
                )}

                {disclaimer && (
                  <div className="partial-index-callout">
                    <div className="disclaimer-title">
                      <Icon name="alert-triangle" size={14} /> Partial Index Coverage Notice
                    </div>
                    <p className="disclaimer-text">{disclaimer}</p>
                  </div>
                )}
              </section>
            )}

            {/* Retrieved Citations List */}
            <section className="source-section">
              <div className="source-section-title">
                Retrieved Sources {hasCitations ? `(${citations.length})` : ''}
              </div>

              {!hasCitations ? (
                <div className="citations-empty-state">
                  <div className="empty-icon">
                    <Icon name="mic" size={26} />
                  </div>
                  <p className="empty-headline">No Retrieved Sources for Current View</p>
                  <p className="empty-subtext">
                    Ask a question about Lenny's Podcast. Retrieved transcript passages with verbatim excerpts
                    and timestamped YouTube links will appear here.
                  </p>
                </div>
              ) : (
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

                        {/* Timestamp & Score Bar */}
                        <div className="citation-meta-row">
                          {cite.timestamp_label && (
                            <span className="citation-timestamp-pill">
                              <Icon name="clock" size={11} /> {cite.timestamp_label}
                            </span>
                          )}
                          {simPercent && (
                            <span className="citation-sim-pill" title="Cosine similarity score">
                              {simPercent}% match
                            </span>
                          )}
                        </div>

                        {/* Verbatim Excerpt */}
                        {cite.content && (
                          <blockquote className="citation-excerpt">
                            "{cite.content}"
                          </blockquote>
                        )}

                        {/* YouTube Link */}
                        {linkUrl && (
                          <div className="citation-link-wrapper">
                            <a
                              href={linkUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="btn-youtube-link"
                              title="Open timestamped video on YouTube"
                            >
                              <Icon name="play" size={11} /> Watch on YouTube{' '}
                              {cite.timestamp_label ? `at ${cite.timestamp_label}` : ''}{' '}
                              <Icon name="external-link" size={11} />
                            </a>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </section>

            {/* Quick Links to Artifacts */}
            <section className="source-section artifact-reserved-section">
              <div className="source-section-title">Artifact Quick Access</div>
              <div className="artifact-quick-buttons">
                <button
                  type="button"
                  className="btn-switch-to-essay"
                  onClick={() => handleTabSwitch('html')}
                >
                  <Icon name="layout" size={13} /> {hasHtmlArtifact ? 'View HTML Artifact' : 'Create HTML Artifact'} →
                </button>
                <button
                  type="button"
                  className="btn-switch-to-essay"
                  onClick={() => handleTabSwitch('essay')}
                >
                  <Icon name="pen" size={13} /> {hasEssay ? 'View Saved Essay' : 'Generate Ship 30 Essay'} →
                </button>
              </div>
            </section>
          </>
        )}
      </div>
    </aside>
  );
}
