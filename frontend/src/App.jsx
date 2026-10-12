import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  fetchHealth,
  fetchSessions,
  createSession,
  updateSession,
  fetchMessages,
  sendPrompt,
  generateEssay,
  fetchLatestEssay,
  generateHtmlArtifact,
  fetchLatestHtmlArtifact,
  fetchProviderConfig,
} from './api.js';
import SafeMarkdown from './SafeMarkdown.jsx';
import SourcePanel from './SourcePanel.jsx';
import HtmlArtifactModal from './HtmlArtifactModal.jsx';
import Icon from './Icon.jsx';

const LOCAL_STORAGE_ACTIVE_SESSION = 'lenny_active_session_id';
const LOCAL_STORAGE_SELECTED_PROVIDER = 'lenny_selected_provider';

const STARTER_PROMPTS = [
  'According to Jason Lemkin, when should founders hire their first salespeople?',
  'What frameworks are most effective for improving B2B SaaS onboarding retention?',
  'What are Elena Verna’s recommendations for freemium vs free trial models?',
  'How should early-stage startups structure their initial growth loops?',
];

/**
 * Generate a concise conversation title from the user's first prompt.
 * Truncates at natural word boundary when length exceeds limit.
 * @param {string} question
 * @returns {string}
 */
function generateConciseTitle(question) {
  if (!question) return 'Untitled Conversation';
  const clean = question.trim().replace(/\s+/g, ' ');
  if (clean.length <= 48) return clean;
  const slice = clean.slice(0, 48);
  const lastSpace = slice.lastIndexOf(' ');
  if (lastSpace > 20) {
    return `${slice.slice(0, lastSpace)}...`;
  }
  return `${slice}...`;
}

/**
 * Format dynamic model indicator label and hint for pending response indicator.
 * @param {Object} provider
 * @returns {{ isCloud: boolean, model: string, label: string, hint: string, providerLabel: string }}
 */
export function getPendingIndicatorInfo(provider) {
  const isCloud = provider?.type === 'cloud' || provider?.id === 'google';
  const model = provider?.model || (isCloud ? 'gemini-3.8-flash' : 'qwen2.5:1.5b');
  const providerLabel = isCloud
    ? `Cloud Google Gemini — ${model}`
    : `Local Ollama — ${model}`;
  const label = `Searching Lenny's Podcast transcripts and generating a grounded response using Pi Coding Agent (${providerLabel})...`;
  const hint = isCloud
    ? 'Transcripts retrieved locally with pgvector embeddings; response generated via Google Gemini cloud inference.'
    : 'Local inference typically takes 20–60 seconds on standard CPU/8 GB RAM.';
  return { isCloud, model, label, hint, providerLabel };
}

/**
 * Format clean, non-redundant model selector option label.
 * E.g., "Local · Ollama (qwen2.5:1.5b)" or "Cloud · Google Gemini (gemini-3.8-flash)"
 * @param {Object} prov
 * @returns {string}
 */
export function formatProviderOptionLabel(prov) {
  if (!prov) return '';
  const typeLabel = prov.type === 'local' ? 'Local' : 'Cloud';
  let cleanName = prov.name || (prov.type === 'local' ? 'Ollama' : 'Google Gemini');
  const match = cleanName.match(/^(?:Local|Cloud)\s*\((.+)\)$/i);
  if (match) {
    cleanName = match[1];
  }
  const unconfiguredNotice = !prov.is_configured ? ' [Key Needed]' : '';
  return `${typeLabel} · ${cleanName} (${prov.model})${unconfiguredNotice}`;
}

export default function App() {
  // Session & conversation state
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  
  // UI states
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [inputText, setInputText] = useState('');
  
  // Collapsible state for grouping untitled conversations (collapsed by default)
  const [isUntitledOpen, setIsUntitledOpen] = useState(false);

  // Group conversations into meaningful titled sessions vs "Untitled Conversation" sessions
  const { titledSessions, untitledSessions, hasActiveUntitled } = useMemo(() => {
    const titled = [];
    const untitled = [];
    for (const s of sessions) {
      const trimmedTitle = (s.title || '').trim();
      if (!trimmedTitle || trimmedTitle === 'Untitled Conversation') {
        untitled.push(s);
      } else {
        titled.push(s);
      }
    }
    const hasActive = untitled.some(s => s.id === activeSessionId);
    return { titledSessions: titled, untitledSessions: untitled, hasActiveUntitled: hasActive };
  }, [sessions, activeSessionId]);
  
  // Active citation and metadata inspector state
  const [activeCitations, setActiveCitations] = useState([]);
  const [activeCoverage, setActiveCoverage] = useState(null);
  const [activeDisclaimer, setActiveDisclaimer] = useState(null);
  const [activeRetrievalStatus, setActiveRetrievalStatus] = useState(null);
  const [activeModel, setActiveModel] = useState('qwen2.5:1.5b');
  const [activeProvider, setActiveProvider] = useState('ollama');

  // Phase 5B Essay State
  const [currentEssay, setCurrentEssay] = useState(null);
  const [isGeneratingEssay, setIsGeneratingEssay] = useState(false);
  const [generatingSessionId, setGeneratingSessionId] = useState(null);
  const [essayError, setEssayError] = useState(null);

  // Phase 6B HTML/CSS Artifact State
  const [currentHtmlArtifact, setCurrentHtmlArtifact] = useState(null);
  const [isGeneratingHtml, setIsGeneratingHtml] = useState(false);
  const [generatingHtmlSessionId, setGeneratingHtmlSessionId] = useState(null);
  const [htmlArtifactError, setHtmlArtifactError] = useState(null);
  const [isHtmlModalOpen, setIsHtmlModalOpen] = useState(false);

  // Active right panel tab: 'html' | 'essay' | 'sources'
  const [activeArtifactTab, setActiveArtifactTab] = useState('html');

  // Dynamic panel resizing state
  const [artifactWidth, setArtifactWidth] = useState(440);
  const [isResizing, setIsResizing] = useState(false);

  // Backend connectivity state
  const [backendStatus, setBackendStatus] = useState({
    online: false,
    version: null,
    model: 'qwen2.5:1.5b',
    provider: 'ollama',
  });

  // Phase 7 Switchable Provider State
  const [providerConfig, setProviderConfig] = useState(null);
  const [selectedProviderId, setSelectedProviderId] = useState(
    () => localStorage.getItem(LOCAL_STORAGE_SELECTED_PROVIDER) || 'ollama'
  );
  const [submittingProviderInfo, setSubmittingProviderInfo] = useState(null);


  const chatBottomRef = useRef(null);
  const textareaRef = useRef(null);
  
  // Stale request guard ref for rapid session switching
  const activeSessionIdRef = useRef(activeSessionId);
  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  // Resizing mouse drag listeners
  const startResizing = (e) => {
    e.preventDefault();
    setIsResizing(true);
  };

  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e) => {
      const newWidth = window.innerWidth - e.clientX;
      if (newWidth >= 320 && newWidth <= Math.min(window.innerWidth - 420, 850)) {
        setArtifactWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing]);

  // Auto-scroll to bottom of chat
  const scrollToBottom = () => {
    if (chatBottomRef.current) {
      chatBottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isSubmitting]);

  // Initial load: Check health and fetch saved sessions
  useEffect(() => {
    let isMounted = true;

    async function initialize() {
      // 1. Health check probe & model capabilities
      try {
        const health = await fetchHealth();
        if (isMounted) {
          setBackendStatus({
            online: health.status === 'ok',
            version: health.version,
            model: health.model || 'qwen2.5:1.5b',
            provider: health.llm_provider || 'ollama',
          });
        }
      } catch (err) {
        if (isMounted) {
          setBackendStatus(prev => ({ ...prev, online: false }));
          console.warn('Backend health probe failed:', err.message);
        }
      }

      // 1b. Fetch switchable provider capabilities
      try {
        const pConfig = await fetchProviderConfig();
        if (isMounted) {
          setProviderConfig(pConfig);
        }
      } catch (err) {
        console.warn('Provider config fetch failed:', err.message);
      }


      // 2. Fetch sessions from PostgreSQL
      try {
        setLoadingSessions(true);
        const data = await fetchSessions(50, 0);
        if (!isMounted) return;

        const sessionItems = data.items || [];
        setSessions(sessionItems);

        // Restore saved session or fallback to first session
        const storedSessionId = localStorage.getItem(LOCAL_STORAGE_ACTIVE_SESSION);
        const matchedSession = sessionItems.find(s => s.id === storedSessionId);

        if (matchedSession) {
          setActiveSessionId(matchedSession.id);
        } else if (sessionItems.length > 0) {
          setActiveSessionId(sessionItems[0].id);
        } else {
          setActiveSessionId(null);
        }
      } catch (err) {
        if (isMounted) {
          setError(`Unable to load conversation sessions: ${err.message}. Ensure backend is running.`);
        }
      } finally {
        if (isMounted) {
          setLoadingSessions(false);
        }
      }
    }

    initialize();
    return () => {
      isMounted = false;
    };
  }, []);

  // When active session changes, load messages and restore latest artifacts from PostgreSQL
  useEffect(() => {
    if (!activeSessionId) {
      setMessages([]);
      setActiveCitations([]);
      setCurrentEssay(null);
      setEssayError(null);
      setCurrentHtmlArtifact(null);
      setHtmlArtifactError(null);
      return;
    }

    let isMounted = true;
    localStorage.setItem(LOCAL_STORAGE_ACTIVE_SESSION, activeSessionId);

    // Immediately clear previous session's artifacts to prevent stale display
    setCurrentEssay(null);
    setEssayError(null);
    setCurrentHtmlArtifact(null);
    setHtmlArtifactError(null);

    const currentSessionId = activeSessionId;

    // Load Messages
    async function loadMessages() {
      try {
        setLoadingMessages(true);
        setError(null);
        const data = await fetchMessages(currentSessionId, 100, 0);
        if (!isMounted || activeSessionIdRef.current !== currentSessionId) return;

        const fetchedMessages = data.items || [];
        setMessages(fetchedMessages);

        // Extract metadata and citations from the latest assistant message
        const lastAssistantMsg = [...fetchedMessages]
          .reverse()
          .find(m => m.role === 'assistant' && m.source_metadata);

        if (lastAssistantMsg && lastAssistantMsg.source_metadata) {
          const meta = lastAssistantMsg.source_metadata;
          setActiveCitations(meta.citations || []);
          setActiveCoverage(meta.coverage || null);
          setActiveDisclaimer(meta.disclaimer || null);
          setActiveRetrievalStatus(meta.retrieval_status || null);
          if (meta.model) setActiveModel(meta.model);
          if (meta.provider) setActiveProvider(meta.provider);
        } else {
          setActiveCitations([]);
          setActiveCoverage(null);
          setActiveDisclaimer(null);
          setActiveRetrievalStatus(null);
        }
      } catch (err) {
        if (isMounted && activeSessionIdRef.current === currentSessionId) {
          setError(`Failed to load messages for this conversation: ${err.message}`);
        }
      } finally {
        if (isMounted && activeSessionIdRef.current === currentSessionId) {
          setLoadingMessages(false);
        }
      }
    }

    // Load Latest Essay Artifact
    async function loadEssay() {
      try {
        const savedEssay = await fetchLatestEssay(currentSessionId);
        if (!isMounted || activeSessionIdRef.current !== currentSessionId) return;
        setCurrentEssay(savedEssay);
        if (savedEssay && !currentHtmlArtifact) {
          setActiveArtifactTab('essay');
        }
      } catch (err) {
        if (isMounted && activeSessionIdRef.current === currentSessionId) {
          console.warn('Failed to restore saved essay:', err.message);
        }
      }
    }

    // Load Latest HTML/CSS Artifact
    async function loadHtmlArtifact() {
      try {
        const savedArtifact = await fetchLatestHtmlArtifact(currentSessionId);
        if (!isMounted || activeSessionIdRef.current !== currentSessionId) return;
        setCurrentHtmlArtifact(savedArtifact);
        if (savedArtifact) {
          setActiveArtifactTab('html');
        }
      } catch (err) {
        if (isMounted && activeSessionIdRef.current === currentSessionId) {
          console.warn('Failed to restore saved HTML artifact:', err.message);
        }
      }
    }

    loadMessages();
    loadEssay();
    loadHtmlArtifact();

    return () => {
      isMounted = false;
    };
  }, [activeSessionId]);

  // Create a new conversation session
  const handleCreateNewSession = async () => {
    try {
      setError(null);
      const newSession = await createSession(null, { client: 'react-web' });
      setSessions(prev => [newSession, ...prev]);
      setActiveSessionId(newSession.id);
      setMessages([]);
      setActiveCitations([]);
      setActiveCoverage(null);
      setActiveDisclaimer(null);
      setActiveRetrievalStatus(null);
      setCurrentEssay(null);
      setEssayError(null);
      setCurrentHtmlArtifact(null);
      setHtmlArtifactError(null);
      setActiveArtifactTab('html');
      if (textareaRef.current) {
        textareaRef.current.focus();
      }
    } catch (err) {
      setError(`Failed to create a new session: ${err.message}`);
    }
  };

  // Switch to a selected session
  const handleSelectSession = (sessionId) => {
    if (sessionId === activeSessionId) return;
    setActiveSessionId(sessionId);
  };

  // Inspect citations from a specific assistant message
  const handleInspectMessageCitations = (msg) => {
    if (msg.source_metadata) {
      const meta = msg.source_metadata;
      setActiveCitations(meta.citations || []);
      if (meta.coverage) setActiveCoverage(meta.coverage);
      if (meta.disclaimer) setActiveDisclaimer(meta.disclaimer);
      if (meta.retrieval_status) setActiveRetrievalStatus(meta.retrieval_status);
      if (meta.model) setActiveModel(meta.model);
      if (meta.provider) setActiveProvider(meta.provider);
      setActiveArtifactTab('sources');
    }
  };

  // Active provider capability object derived from server config
  const activeProviderObj =
    providerConfig?.providers?.find((p) => p.id === selectedProviderId) ||
    providerConfig?.providers?.[0] || {
      id: 'ollama',
      name: 'Local (Ollama)',
      model: 'qwen2.5:1.5b',
      type: 'local',
      is_configured: true,
      description: 'Offline local inference using Ollama with genuine Pi Coding Agent.',
    };

  // Dynamic pending response indicator info locked to current submission
  const pendingIndicatorInfo = getPendingIndicatorInfo(submittingProviderInfo || activeProviderObj);

  // Send a user question
  const handleSendMessage = async (textToSend = null) => {
    const question = (typeof textToSend === 'string' ? textToSend : inputText).trim();
    if (!question || isSubmitting) return;

    // Check if selecting an unconfigured cloud provider
    if (!activeProviderObj.is_configured) {
      setError(
        `Cloud provider '${activeProviderObj.name}' is selected, but credentials are not configured in the backend environment. Please configure GEMINI_API_KEY in the server .env or switch to Local (Ollama).`
      );
      return;
    }

    setError(null);
    setInputText('');

    let currentSessionId = activeSessionId;

    // If no session exists, create an untitled session first
    if (!currentSessionId) {
      try {
        const created = await createSession(null, { client: 'react-web' });
        setSessions(prev => [created, ...prev]);
        setActiveSessionId(created.id);
        currentSessionId = created.id;
      } catch (err) {
        setError(`Failed to initialize session: ${err.message}`);
        setInputText(question);
        return;
      }
    }

    // Check if current session is untitled (first prompt in a new conversation)
    const currentSession = sessions.find(s => s.id === currentSessionId);
    const isUntitled =
      !currentSession ||
      !currentSession.title ||
      currentSession.title === 'Untitled Conversation' ||
      currentSession.title === 'New Conversation';

    // Add optimistic user message to the thread
    const optimisticUserMsg = {
      id: `temp-${Date.now()}`,
      session_id: currentSessionId,
      role: 'user',
      content: question,
      created_at: new Date().toISOString(),
      isOptimistic: true,
    };

    setMessages(prev => [...prev, optimisticUserMsg]);
    // Lock provider metadata for this in-flight submission
    setSubmittingProviderInfo({
      id: activeProviderObj.id,
      name: activeProviderObj.name,
      model: activeProviderObj.model,
      type: activeProviderObj.type,
    });
    setIsSubmitting(true);

    try {
      // Call genuine grounded RAG endpoint with active provider and model
      const response = await sendPrompt(currentSessionId, question, {
        timeoutMs: 120000,
        provider: selectedProviderId,
        model: activeProviderObj.model,
      });

      // Consistently update messages using authoritative records from backend
      setMessages(prev => {
        const withoutTemp = prev.filter(m => !m.isOptimistic);
        const existingIds = new Set(withoutTemp.map(m => m.id));
        const next = [...withoutTemp];

        if (!existingIds.has(response.user_message.id)) {
          next.push(response.user_message);
        }
        if (!existingIds.has(response.assistant_message.id)) {
          next.push(response.assistant_message);
        }
        return next;
      });

      // Update right panel citations and grounding metadata
      const citations = response.citations || response.assistant_message?.source_metadata?.citations || [];
      setActiveCitations(citations);
      setActiveCoverage(response.coverage || null);
      setActiveDisclaimer(response.disclaimer || null);
      setActiveRetrievalStatus(response.retrieval_status || null);
      if (response.model) setActiveModel(response.model);
      if (response.provider) setActiveProvider(response.provider);

      // Persist concise title in PostgreSQL if this was an untitled conversation
      if (isUntitled) {
        const conciseTitle = generateConciseTitle(question);
        try {
          const updated = await updateSession(currentSessionId, { title: conciseTitle });
          setSessions(prev =>
            prev.map(s =>
              s.id === currentSessionId
                ? { ...s, title: updated.title, updated_at: updated.updated_at }
                : s
            )
          );
        } catch (titleErr) {
          console.warn('Failed to persist conversation title to backend:', titleErr.message);
          setSessions(prev =>
            prev.map(s =>
              s.id === currentSessionId ? { ...s, title: conciseTitle } : s
            )
          );
        }
      }
    } catch (err) {
      setError(
        `${err.message || 'Error generating AI response.'} ` +
        'If this was a network interruption, click "Sync Conversation" to inspect persisted messages.'
      );
      // Keep optimistic message marked with error state so user does not lose question
      setMessages(prev =>
        prev.map(m =>
          m.id === optimisticUserMsg.id ? { ...m, hasError: true } : m
        )
      );
    } finally {
      setIsSubmitting(false);
      setSubmittingProviderInfo(null);
    }
  };

  // Generate Ship 30 for 30 digital essay
  const handleGenerateEssay = async ({ topic, audience, target_word_count }) => {
    if (isGeneratingEssay) {
      setEssayError('Another essay generation is currently in progress. Please wait for it to complete.');
      return;
    }

    let targetSessionId = activeSessionId;

    // If no active session, automatically initialize one first
    if (!targetSessionId) {
      try {
        const created = await createSession('Essay Conversation', { client: 'react-web' });
        setSessions(prev => [created, ...prev]);
        setActiveSessionId(created.id);
        targetSessionId = created.id;
      } catch (err) {
        setError(`Failed to create conversation session for essay: ${err.message}`);
        return;
      }
    }

    // Check if selecting an unconfigured cloud provider
    if (!activeProviderObj.is_configured) {
      setEssayError(
        `Cloud provider '${activeProviderObj.name}' is selected, but credentials are not configured in the backend environment. Please configure GEMINI_API_KEY in .env or switch to Local (Ollama).`
      );
      return;
    }

    setGeneratingSessionId(targetSessionId);
    setIsGeneratingEssay(true);
    setEssayError(null);
    setActiveArtifactTab('essay');

    try {
      const response = await generateEssay(
        targetSessionId,
        {
          topic,
          audience,
          target_word_count: target_word_count || 1250,
          provider: selectedProviderId,
          model: activeProviderObj.model,
        },
        { timeoutMs: 960000 }
      );

      // Verify that user hasn't switched sessions while long generation was running
      if (activeSessionIdRef.current === targetSessionId) {
        setCurrentEssay(response);
        // Refresh conversation messages to include persisted essay artifact message
        try {
          const msgsData = await fetchMessages(targetSessionId, 100, 0);
          if (activeSessionIdRef.current === targetSessionId) {
            setMessages(msgsData.items || []);
          }
        } catch {
          // Non-blocking
        }
      }
    } catch (err) {
      if (activeSessionIdRef.current === targetSessionId) {
        setEssayError(err.message || 'Failed to generate essay.');
      }
    } finally {
      setGeneratingSessionId(null);
      setIsGeneratingEssay(false);
    }
  };

  // Generate HTML/CSS design artifact (Phase 6B)
  const handleGenerateHtmlArtifact = async (payload) => {
    if (isGeneratingHtml) {
      setHtmlArtifactError('Another HTML artifact generation is currently in progress. Please wait for it to complete.');
      return;
    }

    // Check if selecting an unconfigured cloud provider
    if (!activeProviderObj.is_configured) {
      setHtmlArtifactError(
        `Cloud provider '${activeProviderObj.name}' is selected, but credentials are not configured in the backend environment. Please configure GEMINI_API_KEY in .env or switch to Local (Ollama).`
      );
      return;
    }

    let targetSessionId = activeSessionId;

    // If no active session, automatically initialize one first
    if (!targetSessionId) {
      try {
        const sessionTitle = payload.title || 'HTML Design Session';
        const created = await createSession(sessionTitle, { client: 'react-web' });
        setSessions(prev => [created, ...prev]);
        setActiveSessionId(created.id);
        targetSessionId = created.id;
      } catch (err) {
        setError(`Failed to create conversation session for HTML artifact: ${err.message}`);
        return;
      }
    }

    // Check if selecting an unconfigured cloud provider
    if (!activeProviderObj.is_configured) {
      setHtmlArtifactError(
        `Cloud provider '${activeProviderObj.name}' is selected, but credentials are not configured in the backend environment. Please configure GEMINI_API_KEY in .env or switch to Local (Ollama).`
      );
      return;
    }

    setGeneratingHtmlSessionId(targetSessionId);
    setIsGeneratingHtml(true);
    setHtmlArtifactError(null);
    setActiveArtifactTab('html');
    setIsHtmlModalOpen(false);

    try {
      const response = await generateHtmlArtifact(
        targetSessionId,
        {
          ...payload,
          provider: selectedProviderId,
          model: activeProviderObj.model,
        },
        { timeoutMs: 240000 }
      );

      // Verify that user hasn't switched sessions while generation was running
      if (activeSessionIdRef.current === targetSessionId) {
        setCurrentHtmlArtifact(response);
        // Refresh conversation messages to include persisted artifact message
        try {
          const msgsData = await fetchMessages(targetSessionId, 100, 0);
          if (activeSessionIdRef.current === targetSessionId) {
            setMessages(msgsData.items || []);
          }
        } catch {
          // Non-blocking
        }
      }
    } catch (err) {
      if (activeSessionIdRef.current === targetSessionId) {
        setHtmlArtifactError(err.message || 'Failed to generate HTML artifact.');
      }
    } finally {
      setGeneratingHtmlSessionId(null);
      setIsGeneratingHtml(false);
    }
  };

  // Keyboard shortcut: Enter to submit, Shift+Enter for newline
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // Manually sync conversation history from PostgreSQL after recoverable error
  const handleSyncHistory = async () => {
    if (!activeSessionId) return;
    try {
      setLoadingMessages(true);
      setError(null);
      const data = await fetchMessages(activeSessionId, 100, 0);
      setMessages(data.items || []);
      const essay = await fetchLatestEssay(activeSessionId);
      setCurrentEssay(essay);
      const artifact = await fetchLatestHtmlArtifact(activeSessionId);
      setCurrentHtmlArtifact(artifact);
    } catch (err) {
      setError(`Failed to sync history: ${err.message}`);
    } finally {
      setLoadingMessages(false);
    }
  };

  return (
    <div className={`app-layout ${isResizing ? 'is-resizing' : ''}`}>
      {/* Header */}
      <header className="app-header">
        <div className="brand-section">
          <div className="brand-icon">
            <Icon name="mic" size={18} />
          </div>
          <div>
            <h1 className="brand-title">Lenny Growth Assistant</h1>
            <p className="brand-subtitle">Product & Growth Intelligence from Lenny's Podcast</p>
          </div>
        </div>

        <div className="header-status-group">
          {/* Create HTML Artifact Header Action */}
          <button
            type="button"
            className="btn-header-artifact"
            onClick={() => setIsHtmlModalOpen(true)}
            title="Create a modern, responsive HTML/CSS design artifact"
          >
            <Icon name="layout" size={14} /> Create HTML Artifact
          </button>

          {/* Discoverable Essay Generation Header Action */}
          <button
            type="button"
            className="btn-header-essay"
            onClick={() => setActiveArtifactTab('essay')}
            title="Generate or view Ship 30 for 30 digital essay"
          >
            <Icon name="pen" size={14} /> Generate Essay
          </button>

          <span className={`badge ${backendStatus.online ? 'badge-backend-online' : 'badge-backend-offline'}`}>
            <span className={`pulse-dot ${backendStatus.online ? '' : 'pulse-dot-offline'}`}></span>
            {backendStatus.online ? 'Backend: Connected' : 'Backend: Offline'}
          </span>
          {/* Phase 7 Provider & Model Switcher */}
          <div className="provider-selector-container">
            <div className="provider-selector-box">
              <span className="provider-icon">
                <Icon name={activeProviderObj.type === 'local' ? 'monitor' : 'cloud'} size={14} />
              </span>
              <select
                id="model-provider-select"
                className={`provider-select-dropdown ${!activeProviderObj.is_configured ? 'provider-select-warn' : ''}`}
                value={selectedProviderId}
                onChange={(e) => {
                  const newId = e.target.value;
                  setSelectedProviderId(newId);
                  localStorage.setItem(LOCAL_STORAGE_SELECTED_PROVIDER, newId);
                }}
                aria-label="Select LLM Provider and Model"
                title={activeProviderObj.description}
              >
                {providerConfig?.providers?.map((prov) => (
                  <option key={prov.id} value={prov.id}>
                    {formatProviderOptionLabel(prov)}
                  </option>
                )) || (
                  <option value="ollama">Local · Ollama (qwen2.5:1.5b)</option>
                )}
              </select>
            </div>
            {!activeProviderObj.is_configured && (
              <span
                className="provider-unconfigured-pill"
                title="API key not found in backend environment. Configure GEMINI_API_KEY in .env to run cloud inference."
              >
                <Icon name="alert-triangle" size={12} /> Key Needed
              </span>
            )}
          </div>
          <span className="badge badge-phase">
            Local & Cloud
          </span>
        </div>
      </header>

      {/* Main Split View: Left Sidebar + Center Chat + Right Source/Artifact Panel */}
      <div className="main-workspace">
        {/* Left Panel: Conversation Sessions */}
        <aside className="session-sidebar" aria-label="Conversation Sessions">
          <div className="sidebar-header">
            <button
              className="btn-new-session-active"
              onClick={handleCreateNewSession}
              title="Start a new conversation"
            >
              <Icon name="plus" size={14} /> New Conversation
            </button>
          </div>

          <div className="sidebar-sessions-list">
            <div className="sidebar-section-title">Saved Conversations</div>

            {loadingSessions ? (
              <div className="sidebar-loading-state">
                <span className="mini-spinner"></span> Loading conversations...
              </div>
            ) : sessions.length === 0 ? (
              <div className="sidebar-empty-state">
                <p>No conversations yet.</p>
                <p className="sidebar-empty-sub">Click "+ New Conversation" above to start.</p>
              </div>
            ) : (
              <>
                {/* Conversations with meaningful titles */}
                {titledSessions.map(s => {
                  const isSelected = s.id === activeSessionId;
                  const displayTitle = s.title || 'Untitled Conversation';
                  const dateLabel = s.created_at
                    ? new Date(s.created_at).toLocaleDateString([], {
                        month: 'short',
                        day: 'numeric',
                      })
                    : '';

                  return (
                    <button
                      key={s.id}
                      className={`session-item-btn ${isSelected ? 'selected' : ''}`}
                      onClick={() => handleSelectSession(s.id)}
                    >
                      <div className="session-item-title" title={displayTitle}>
                        {displayTitle}
                      </div>
                      <div className="session-item-meta">
                        <span>{dateLabel}</span>
                        {isSelected && <span className="active-tag">Active</span>}
                      </div>
                    </button>
                  );
                })}

                {/* Collapsible section for Untitled Conversations */}
                {untitledSessions.length > 0 && (
                  <div className="untitled-conversations-section">
                    <button
                      type="button"
                      className={`untitled-accordion-header ${isUntitledOpen ? 'expanded' : ''} ${hasActiveUntitled ? 'contains-active' : ''}`}
                      onClick={() => setIsUntitledOpen(prev => !prev)}
                      aria-expanded={isUntitledOpen}
                      title={isUntitledOpen ? 'Collapse untitled conversations' : 'Expand untitled conversations'}
                    >
                      <div className="untitled-header-main">
                        <Icon
                          name={isUntitledOpen ? 'chevron-down' : 'chevron-right'}
                          size={13}
                          className="untitled-chevron-icon"
                        />
                        <span className="untitled-header-label">
                          Untitled conversations ({untitledSessions.length})
                        </span>
                      </div>
                      {hasActiveUntitled && !isUntitledOpen && (
                        <span className="active-tag active-tag-subtle" title="Active conversation is inside this section">
                          Active
                        </span>
                      )}
                    </button>

                    {isUntitledOpen && (
                      <div className="untitled-conversations-list">
                        {untitledSessions.map(s => {
                          const isSelected = s.id === activeSessionId;
                          const displayTitle = s.title || 'Untitled Conversation';
                          const dateLabel = s.created_at
                            ? new Date(s.created_at).toLocaleDateString([], {
                                month: 'short',
                                day: 'numeric',
                              })
                            : '';

                          return (
                            <button
                              key={s.id}
                              className={`session-item-btn session-item-untitled ${isSelected ? 'selected' : ''}`}
                              onClick={() => handleSelectSession(s.id)}
                            >
                              <div className="session-item-title" title={displayTitle}>
                                {displayTitle}
                              </div>
                              <div className="session-item-meta">
                                <span>{dateLabel}</span>
                                {isSelected && <span className="active-tag">Active</span>}
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </aside>

        {/* Center Panel: Active Conversation & Composer */}
        <main className="chat-container">
          {/* Error Banner */}
          {error && (
            <div className="error-banner" role="alert">
              <div className="error-banner-content">
                <span className="error-icon">
                  <Icon name="alert-triangle" size={15} />
                </span>
                <span className="error-text">{error}</span>
              </div>
              <div className="error-banner-actions">
                {activeSessionId && (
                  <button className="btn-error-sync" onClick={handleSyncHistory}>
                    Sync Conversation
                  </button>
                )}
                <button className="btn-error-dismiss" onClick={() => setError(null)}>
                  <Icon name="x" size={13} />
                </button>
              </div>
            </div>
          )}

          {/* Chat Viewport */}
          <div className="chat-viewport">
            {loadingMessages ? (
              <div className="chat-loading-state">
                <div className="loading-spinner"></div>
                <p>Loading conversation history from PostgreSQL...</p>
              </div>
            ) : messages.length === 0 ? (
              /* Hero Empty State with Starter Prompts & Artifact Actions */
              <div className="placeholder-hero-card">
                <div className="hero-icon">
                  <Icon name="sparkles" size={26} />
                </div>
                <h2 className="hero-title">Grounded Podcast Intelligence & Artifacts</h2>
                <p className="hero-description">
                  Ask product management, growth loop, hiring, and startup strategy questions 
                  grounded strictly in authentic transcripts from Lenny's Podcast, or synthesize 
                  insights into essays and HTML/CSS web layouts.
                </p>

                <div className="status-callout">
                  <strong>Live System Status:</strong><br />
                  Connected to PostgreSQL persistence, pgvector semantic search, and 
                  genuine Pi Coding Agent with {activeProviderObj.type === 'cloud' ? 'cloud' : 'local'} <code>{activeProviderObj.model}</code> ({activeProviderObj.name}).
                </div>

                <div className="starter-prompts-title">Sample Growth Questions & Artifacts:</div>
                <div className="starter-prompts-grid">
                  {STARTER_PROMPTS.map((prompt, idx) => (
                    <button
                      key={idx}
                      className="starter-prompt-card"
                      onClick={() => handleSendMessage(prompt)}
                      disabled={isSubmitting}
                    >
                      <span className="prompt-arrow">→</span>
                      <span>{prompt}</span>
                    </button>
                  ))}

                  {/* Create HTML/CSS Artifact Shortcut Card */}
                  <button
                    className="starter-prompt-card starter-artifact-card"
                    onClick={() => setIsHtmlModalOpen(true)}
                    disabled={isGeneratingHtml}
                  >
                    <span className="prompt-arrow">
                      <Icon name="layout" size={14} />
                    </span>
                    <span>
                      <strong>Create HTML/CSS Artifact:</strong> Generate landing pages, dashboards & UI components with Pi Agent
                    </span>
                  </button>

                  {/* Discoverable Essay Generator Shortcut Card */}
                  <button
                    className="starter-prompt-card starter-essay-card"
                    onClick={() => setActiveArtifactTab('essay')}
                    disabled={isGeneratingEssay}
                  >
                    <span className="prompt-arrow">
                      <Icon name="pen" size={14} />
                    </span>
                    <span>
                      <strong>Generate Ship 30 Essay:</strong> Synthesize podcast frameworks into a ~1,250-word digital essay
                    </span>
                  </button>
                </div>
              </div>
            ) : (
              /* Message History Stream */
              <div className="messages-thread">
                {messages.map((msg, index) => {
                  const isUser = msg.role === 'user';
                  const citations = msg.source_metadata?.citations || [];
                  const disclaimer = msg.source_metadata?.disclaimer;
                  const retrievalStatus = msg.source_metadata?.retrieval_status;
                  const isEssayArtifact = msg.source_metadata?.artifact_type === 'ship30_essay';
                  const isHtmlArtifact = msg.source_metadata?.artifact_type === 'html_artifact';

                  return (
                    <div
                      key={msg.id || index}
                      className={`message-row ${isUser ? 'user-row' : 'assistant-row'}`}
                    >
                      <div className={`message-avatar ${isUser ? 'user-avatar' : 'assistant-avatar'}`}>
                        {isUser ? (
                          <Icon name="user" size={16} />
                        ) : isHtmlArtifact ? (
                          <Icon name="layout" size={16} />
                        ) : isEssayArtifact ? (
                          <Icon name="pen" size={16} />
                        ) : (
                          <Icon name="mic" size={16} />
                        )}
                      </div>

                      <div className={`message-bubble ${isUser ? 'user-bubble' : 'assistant-bubble'}`}>
                        {/* Message Header */}
                        <div className="message-header">
                          <span className="message-sender">
                            {isUser
                              ? 'You'
                              : isHtmlArtifact
                              ? 'HTML/CSS Artifact Generator'
                              : isEssayArtifact
                              ? 'Ship 30 for 30 Essay Generator'
                              : 'Lenny Growth Assistant'}
                          </span>
                          <span className="message-timestamp">
                            {msg.created_at
                              ? new Date(msg.created_at).toLocaleTimeString([], {
                                  hour: '2-digit',
                                  minute: '2-digit',
                                })
                              : ''}
                          </span>
                        </div>

                        {/* Message Content */}
                        <div className="message-body">
                          {isUser ? (
                            <p className="user-text">{msg.content}</p>
                          ) : (
                            <SafeMarkdown content={msg.content} />
                          )}
                        </div>

                        {/* Partial Index Disclaimer Callout */}
                        {!isUser && disclaimer && (
                          <div className="message-disclaimer-callout">
                            <span className="disclaimer-badge">Notice</span>
                            <span className="disclaimer-inline-text">{disclaimer}</span>
                          </div>
                        )}

                        {/* Assistant Source Metadata & Citations Footer */}
                        {!isUser && (
                          <div className="message-footer-meta">
                            <div className="meta-left-group">
                              {retrievalStatus && (
                                <span
                                  className={`meta-badge ${
                                    retrievalStatus === 'success'
                                      ? 'badge-retrieval-success'
                                      : 'badge-retrieval-warn'
                                  }`}
                                >
                                  {retrievalStatus === 'success' ? (
                                    <>
                                      <Icon name="check" size={11} /> Transcripts Retrieved
                                    </>
                                  ) : (
                                    <>
                                      <Icon name="alert-triangle" size={11} /> Insufficient Evidence
                                    </>
                                  )}
                                </span>
                              )}
                              <span className="meta-badge badge-model-tag">
                                {msg.source_metadata?.model || activeModel}
                              </span>
                              {isHtmlArtifact && (
                                <span className="meta-badge badge-html-artifact-tag">
                                  <Icon name="layout" size={12} /> HTML/CSS Artifact
                                </span>
                              )}
                              {isEssayArtifact && (
                                <span className="meta-badge badge-essay-artifact-tag">
                                  <Icon name="pen" size={12} /> Ship 30 Essay
                                </span>
                              )}
                            </div>

                            <div className="meta-right-group">
                              {isHtmlArtifact && (
                                <button
                                  type="button"
                                  className="btn-inspect-artifact"
                                  onClick={() => setActiveArtifactTab('html')}
                                  title="Open HTML artifact in right preview panel"
                                >
                                  View in Preview Panel →
                                </button>
                              )}
                              {isEssayArtifact && (
                                <button
                                  type="button"
                                  className="btn-inspect-essay"
                                  onClick={() => setActiveArtifactTab('essay')}
                                  title="Open essay in the artifact panel"
                                >
                                  View in Artifact Panel →
                                </button>
                              )}
                              {citations.length > 0 && (
                                <button
                                  className="btn-inspect-citations"
                                  onClick={() => handleInspectMessageCitations(msg)}
                                  title="View retrieved sources in right panel"
                                >
                                  <Icon name="book-open" size={12} /> {citations.length} {citations.length === 1 ? 'Citation' : 'Citations'}
                                </button>
                              )}
                            </div>
                          </div>
                        )}

                        {msg.hasError && (
                          <div className="optimistic-error-tag">
                            <Icon name="alert-triangle" size={14} /> Network error during response. Check server logs or click "Sync Conversation".
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}

                {/* Visible Thinking Indicator while LLM processes request */}
                {isSubmitting && (
                  <div className="message-row assistant-row submitting-row">
                    <div className="message-avatar assistant-avatar">
                      <Icon name="mic" size={16} />
                    </div>
                    <div className="message-bubble assistant-bubble submitting-bubble">
                      <div className="submitting-header">
                        <span className="message-sender">Lenny Growth Assistant</span>
                        <span className="submitting-badge">Processing</span>
                      </div>
                      <div className="submitting-content">
                        <div className="thinking-dots">
                          <span className="dot dot-1"></span>
                          <span className="dot dot-2"></span>
                          <span className="dot dot-3"></span>
                        </div>
                        <p className="submitting-label">
                          Searching Lenny's Podcast transcripts and generating a grounded response using Pi Coding Agent ({pendingIndicatorInfo.isCloud ? (
                            <>Cloud Google Gemini — <code>{pendingIndicatorInfo.model}</code></>
                          ) : (
                            <>Local Ollama — <code>{pendingIndicatorInfo.model}</code></>
                          )})...
                        </p>
                        <p className="submitting-hint">
                          {pendingIndicatorInfo.hint}
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                <div ref={chatBottomRef} />
              </div>
            )}
          </div>

          {/* Chat Composer Bar */}
          <div className="chat-input-bar">
            <div className="input-wrapper">
              <textarea
                ref={textareaRef}
                className="chat-textarea"
                rows={1}
                placeholder={
                  isSubmitting
                    ? 'AI is generating response... please wait...'
                    : 'Ask about Lenny\'s Podcast (e.g., Jason Lemkin on sales hiring, retention loops)...'
                }
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isSubmitting}
              />
              <button
                type="button"
                className="btn-artifact-quick-open"
                onClick={() => setIsHtmlModalOpen(true)}
                title="Create a responsive HTML/CSS design artifact"
              >
                <Icon name="layout" size={13} /> HTML
              </button>
              <button
                type="button"
                className="btn-essay-quick-open"
                onClick={() => setActiveArtifactTab('essay')}
                title="Open Ship 30 for 30 digital essay generator"
              >
                <Icon name="pen" size={13} /> Essay
              </button>
              <button
                className="chat-submit-btn"
                type="button"
                onClick={() => handleSendMessage()}
                disabled={isSubmitting || !inputText.trim()}
                title="Send message (Enter)"
              >
                {isSubmitting ? (
                  <span className="btn-thinking-spinner">
                    <Icon name="loader" size={14} className="spin" />
                  </span>
                ) : (
                  <span>Send</span>
                )}
              </button>
            </div>
            <div className="input-helper-text">
              Press <strong>Enter</strong> to send, <strong>Shift + Enter</strong> for new line. Click <strong>HTML</strong> to build a web design, or <strong>Essay</strong> for a 1,250-word essay.
            </div>
          </div>
        </main>

        {/* Resizer Splitter between Center Chat and Right Panel */}
        <div
          className={`panel-resizer ${isResizing ? 'resizing' : ''}`}
          onMouseDown={startResizing}
          title="Drag to resize artifact viewer"
          role="separator"
          aria-orientation="vertical"
        />

        {/* Right Panel: Source Citations, Essay & HTML Artifact Viewers */}
        <SourcePanel
          citations={activeCitations}
          coverage={activeCoverage}
          disclaimer={activeDisclaimer}
          retrievalStatus={activeRetrievalStatus}
          model={activeModel}
          provider={activeProvider}
          essay={currentEssay}
          isGeneratingEssay={isGeneratingEssay && generatingSessionId === activeSessionId}
          essayError={essayError}
          onGenerateEssay={handleGenerateEssay}
          htmlArtifact={currentHtmlArtifact}
          isGeneratingHtml={isGeneratingHtml && generatingHtmlSessionId === activeSessionId}
          htmlArtifactError={htmlArtifactError}
          onOpenHtmlModal={() => setIsHtmlModalOpen(true)}
          activeSessionId={activeSessionId}
          onCreateSession={handleCreateNewSession}
          activeTab={activeArtifactTab}
          onTabChange={setActiveArtifactTab}
          width={artifactWidth}
          activeProvider={activeProviderObj}
        />
      </div>

      {/* Centered Floating Modal Dialog for HTML Artifact Creation */}
      <HtmlArtifactModal
        isOpen={isHtmlModalOpen}
        onClose={() => setIsHtmlModalOpen(false)}
        onSubmit={handleGenerateHtmlArtifact}
        isGenerating={isGeneratingHtml}
        activeSessionId={activeSessionId}
        activeProvider={activeProviderObj}
      />
    </div>
  );
}
