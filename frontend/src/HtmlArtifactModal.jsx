import React, { useState, useEffect, useRef } from 'react';
import { validateArtifactPrompt } from './api.js';

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
      className="modal-backdrop"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby="artifact-modal-title"
    >
      <div className="modal-container">
        {/* Header */}
        <div className="modal-header">
          <div className="modal-header-icon-group">
            <span className="modal-header-icon">🎨</span>
            <div>
              <h2 id="artifact-modal-title" className="modal-title">
                Create HTML/CSS Artifact
              </h2>
              <p className="modal-subtitle">
                Generate responsive, sanitized web layouts powered by Pi Coding Agent &amp;{' '}
                <span className="modal-model-badge">
                  {activeProvider
                    ? `${activeProvider.type === 'local' ? '💻' : '☁️'} ${activeProvider.name}`
                    : "Pi Agent"}
                </span>
              </p>
            </div>
          </div>
          <button
            type="button"
            className="modal-close-btn btn-modal-close"
            onClick={onClose}
            disabled={isGenerating}
            aria-label="Close dialog"
            title="Close (Esc)"
          >
            ✕
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="modal-form">
          <div className="modal-body">
            {/* Description / Prompt */}
            <div className="form-group">
              <label htmlFor="artifact-prompt-input" className="form-label required-label">
                Artifact Description
              </label>
              <textarea
                id="artifact-prompt-input"
                ref={textareaRef}
                className="form-textarea"
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
              <div className="form-group">
                <label htmlFor="artifact-type-select" className="form-label">
                  Artifact Category
                </label>
                <select
                  id="artifact-type-select"
                  className="form-select"
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

              <div className="form-group">
                <label htmlFor="artifact-title-input" className="form-label">
                  Artifact Title <span className="optional-tag">(Optional)</span>
                </label>
                <input
                  id="artifact-title-input"
                  type="text"
                  className="form-input"
                  placeholder="e.g., Growth Loop Landing Page"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  disabled={isGenerating}
                  maxLength={200}
                />
              </div>
            </div>

            {/* Design & Style Preferences */}
            <div className="form-group">
              <label htmlFor="artifact-style-preset" className="form-label">
                Design & Style Aesthetic
              </label>
              <select
                id="artifact-style-preset"
                className="form-select"
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
                  className="form-input custom-style-input"
                  placeholder="Specify palette, typography, visual constraints..."
                  value={customStyle}
                  onChange={(e) => setCustomStyle(e.target.value)}
                  disabled={isGenerating}
                  maxLength={500}
                />
              )}
            </div>

            {/* Podcast Evidence Grounding Checkbox */}
            <div className={`form-checkbox-card ${includePodcastContext ? 'is-checked' : ''}`}>
              <label htmlFor="artifact-include-podcast" className="checkbox-label-container">
                <input
                  id="artifact-include-podcast"
                  type="checkbox"
                  className="form-checkbox"
                  checked={includePodcastContext}
                  onChange={(e) => setIncludePodcastContext(e.target.checked)}
                  disabled={isGenerating}
                />
                <div className="checkbox-text-group">
                  <span className="checkbox-title">
                    Grounded in Lenny's Podcast Frameworks
                  </span>
                  <span className="checkbox-description">
                    Retrieve relevant expert transcript passages and embed verified citations directly into the design copy.
                  </span>
                </div>
              </label>
            </div>

            {/* Validation Error Banner */}
            {validationError && (
              <div className="form-error-alert" role="alert">
                <span>⚠️</span> {validationError}
              </div>
            )}
          </div>

          {/* Footer Controls */}
          <div className="modal-footer">
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
                  <span className="btn-spinner-icon">⏳</span>
                  <span>Generating Artifact...</span>
                </>
              ) : (
                <>
                  <span>✨</span>
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
