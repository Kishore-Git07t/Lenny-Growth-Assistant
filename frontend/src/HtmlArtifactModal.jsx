import React, { useState, useEffect, useRef } from 'react';
import { validateArtifactPrompt } from './api.js';
import Icon from './Icon.jsx';

const CATEGORY_OPTIONS = [
  { value: 'landing_page', label: 'Landing Page' },
  { value: 'dashboard', label: 'Analytics Dashboard' },
  { value: 'marketing_page', label: 'Marketing Page' },
  { value: 'product_showcase', label: 'Product Showcase' },
  { value: 'component', label: 'UI Component' },
  { value: 'custom', label: 'Custom Layout' },
];

const STYLE_PRESETS = [
  'Modern SaaS with smooth gradients and high contrast',
  'Minimal & Clean with elegant typography',
  'Professional Corporate with structured cards',
  'Bold & Colorful with vibrant accents',
  'Dark Theme with sleek borders and glassmorphism',
  'Custom Description',
];

/**
 * Centered modal dialog for creating HTML/CSS design artifacts.
 * Styled with luxury enterprise palette (deep charcoal header, soft ivory reading surfaces,
 * emerald primary accents, and champagne-gold brand badge).
 */
export default function HtmlArtifactModal({
  isOpen,
  onClose,
  onSubmit,
  isGenerating = false,
  activeSessionId = null,
  activeProvider = null,
}) {
  const [prompt, setPrompt] = useState('');
  const [title, setTitle] = useState('');
  const [artifactType, setArtifactType] = useState('landing_page');
  const [stylePreset, setStylePreset] = useState(STYLE_PRESETS[0]);
  const [customStyle, setCustomStyle] = useState('');
  const [includePodcastContext, setIncludePodcastContext] = useState(true);
  const [validationError, setValidationError] = useState('');

  const textareaRef = useRef(null);

  // Autofocus when modal opens
  useEffect(() => {
    if (isOpen) {
      setValidationError('');
      setTimeout(() => {
        if (textareaRef.current) {
          textareaRef.current.focus();
        }
      }, 50);
    }
  }, [isOpen]);

  // Support Escape key to close modal
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && !isGenerating) {
        e.preventDefault();
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, isGenerating, onClose]);

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    setValidationError('');

    const error = validateArtifactPrompt(prompt);
    if (error) {
      setValidationError(error);
      return;
    }

    const resolvedStyle =
      stylePreset === 'Custom Description'
        ? customStyle.trim() || 'Modern SaaS'
        : stylePreset;

    onSubmit({
      prompt: prompt.trim(),
      title: title.trim() || null,
      artifact_type: artifactType,
      style_preferences: resolvedStyle,
      include_podcast_context: includePodcastContext,
    });
  };

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget && !isGenerating) {
      onClose();
    }
  };

  return (
    <div
      className="artifact-modal-overlay modal-backdrop"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      <div className="artifact-modal-container modal-container">
        {/* Header */}
        <div className="modal-header-gradient modal-header">
          <div className="modal-header-content">
            <span className="modal-brand-badge">
              <Icon name="layout" size={12} />
              <span>Pi Coding Agent · Design Artifact</span>
            </span>
            <h2 id="modal-title" className="modal-title-text modal-title">
              Create HTML/CSS Artifact
            </h2>
            <p className="modal-subtitle-text modal-subtitle">
              Generate responsive, sanitized web layouts powered by Pi Coding Agent &amp;{' '}
              <span className="modal-model-badge">
                {activeProvider ? (
                  <>
                    <Icon name={activeProvider.type === 'local' ? 'monitor' : 'cloud'} size={12} />
                    <span>{activeProvider.name}</span>
                  </>
                ) : (
                  <span>Pi Agent</span>
                )}
              </span>
            </p>
          </div>
          <button
            type="button"
            className="btn-modal-close modal-close-btn"
            onClick={onClose}
            disabled={isGenerating}
            aria-label="Close dialog"
            title="Close (Esc)"
          >
            <Icon name="x" size={14} />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="modal-form">
          <div className="modal-form-scrollable modal-body">
            {/* Description / Prompt */}
            <div className="modal-field-group form-group">
              <label htmlFor="artifact-prompt-input" className="modal-label form-label required-label">
                Artifact Description
              </label>
              <textarea
                id="artifact-prompt-input"
                ref={textareaRef}
                className="modal-textarea form-textarea"
                rows={4}
                placeholder="e.g., Create a modern SaaS landing page for an AI growth assistant with a hero section, feature cards, pricing section and strong call-to-action."
                value={prompt}
                onChange={(e) => {
                  setPrompt(e.target.value);
                  if (validationError) setValidationError('');
                }}
                disabled={isGenerating}
                maxLength={4000}
                required
              />
              <div className="form-helper-row">
                <span className="form-hint">
                  Be specific about layout sections, components, and target audience.
                </span>
                <span className={`char-counter ${prompt.length > 3800 ? 'counter-warn' : ''}`}>
                  {prompt.length} / 4000
                </span>
              </div>
            </div>

            {/* Category & Title 2-Column Row */}
            <div className="form-row-2col">
              <div className="modal-field-group form-group">
                <label htmlFor="artifact-type-select" className="modal-label form-label">
                  Artifact Category
                </label>
                <select
                  id="artifact-type-select"
                  className="modal-select form-select"
                  value={artifactType}
                  onChange={(e) => setArtifactType(e.target.value)}
                  disabled={isGenerating}
                >
                  {CATEGORY_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="modal-field-group form-group">
                <label htmlFor="artifact-title-input" className="modal-label form-label">
                  Artifact Title <span className="optional-tag">(Optional)</span>
                </label>
                <input
                  id="artifact-title-input"
                  type="text"
                  className="modal-input form-input"
                  placeholder="e.g., Growth Loop Landing Page"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  disabled={isGenerating}
                  maxLength={200}
                />
              </div>
            </div>

            {/* Design & Style Preferences */}
            <div className="modal-field-group form-group">
              <label htmlFor="artifact-style-preset" className="modal-label form-label">
                Design &amp; Style Aesthetic
              </label>
              <select
                id="artifact-style-preset"
                className="modal-select form-select"
                value={stylePreset}
                onChange={(e) => setStylePreset(e.target.value)}
                disabled={isGenerating}
              >
                {STYLE_PRESETS.map((preset) => (
                  <option key={preset} value={preset}>
                    {preset}
                  </option>
                ))}
              </select>

              {stylePreset === 'Custom Description' && (
                <input
                  type="text"
                  className="modal-input form-input custom-style-input"
                  placeholder="Specify palette, typography, visual constraints..."
                  value={customStyle}
                  onChange={(e) => setCustomStyle(e.target.value)}
                  disabled={isGenerating}
                  maxLength={500}
                />
              )}
            </div>

            {/* Podcast Evidence Grounding Checkbox */}
            <div className={`modal-checkbox-card form-checkbox-card ${includePodcastContext ? 'is-checked' : ''}`}>
              <label htmlFor="artifact-include-podcast" className="accessible-checkbox-label checkbox-label-container">
                <input
                  id="artifact-include-podcast"
                  type="checkbox"
                  className="modal-checkbox-input form-checkbox"
                  checked={includePodcastContext}
                  onChange={(e) => setIncludePodcastContext(e.target.checked)}
                  disabled={isGenerating}
                />
                <div className="checkbox-text-group">
                  <span className="checkbox-title">
                    Grounded in Lenny's Podcast Frameworks
                  </span>
                  <span className="checkbox-desc checkbox-description">
                    Retrieve relevant expert transcript passages and embed verified citations directly into the design copy.
                  </span>
                </div>
              </label>
            </div>

            {/* Validation Error Banner */}
            {validationError && (
              <div className="form-error-alert" role="alert">
                <Icon name="alert-triangle" size={15} />
                <span>{validationError}</span>
              </div>
            )}
          </div>

          {/* Footer Controls */}
          <div className="modal-footer-actions modal-footer">
            <button
              type="button"
              className="btn-modal-cancel btn-modal-secondary"
              onClick={onClose}
              disabled={isGenerating}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-modal-submit btn-modal-primary"
              disabled={isGenerating || !prompt.trim()}
            >
              {isGenerating ? (
                <>
                  <Icon name="loader" size={14} className="spin" />
                  <span>Generating Artifact...</span>
                </>
              ) : (
                <>
                  <Icon name="sparkles" size={14} />
                  <span>Generate Artifact</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
