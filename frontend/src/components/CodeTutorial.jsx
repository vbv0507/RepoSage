import React, { useState, useEffect, useRef } from 'react';
import mermaid from 'mermaid';
import { BookOpen, Download, RefreshCw, CheckCircle2, ChevronRight, ChevronLeft, Sparkles, AlertCircle, Mail, Send, ExternalLink, X, Copy, Check } from 'lucide-react';
import { cleanMermaidCode } from '../utils/mermaidCleaner';

// Initialize mermaid with suppressErrorRendering: true to prevent error bombs
mermaid.initialize({
  startOnLoad: false,
  suppressErrorRendering: true,
  theme: 'dark',
  themeVariables: {
    darkMode: true,
    background: '#0c0c0e',
    primaryColor: '#2563eb',
    primaryTextColor: '#f4f4f5',
    primaryBorderColor: '#3f3f46',
    lineColor: '#71717a',
    secondaryColor: '#18181b',
    tertiaryColor: '#27272a'
  },
  securityLevel: 'loose'
});

export default function CodeTutorial({ activeRepo }) {
  const [tutorial, setTutorial] = useState(null);
  const [activeChapterIndex, setActiveChapterIndex] = useState(0);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatingStep, setGeneratingStep] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Email PDF & Queue state
  const [showEmailModal, setShowEmailModal] = useState(false);
  const [emailInput, setEmailInput] = useState('');
  const [emailJobId, setEmailJobId] = useState(null);
  const [emailJobStatus, setEmailJobStatus] = useState(null);
  const [isSubmittingEmail, setIsSubmittingEmail] = useState(false);
  const [emailError, setEmailError] = useState(null);
  const pollIntervalRef = useRef(null);

  useEffect(() => {
    // Purge any orphan Mermaid error SVGs lingering in document.body
    const purgeErrors = () => {
      document.querySelectorAll('body > svg[id^="dmmd_"]').forEach(el => el.remove());
      document.querySelectorAll('body > [aria-roledescription="error"]').forEach(el => el.remove());
      document.querySelectorAll('body > [id^="dmmd_"]').forEach(el => el.remove());
    };
    purgeErrors();
    return () => {
      purgeErrors();
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const handleSendEmail = async (e) => {
    if (e) e.preventDefault();
    if (!emailInput || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailInput)) {
      setEmailError('Please enter a valid email address.');
      return;
    }
    if (!activeRepo) {
      setEmailError('No active repository selected.');
      return;
    }

    setEmailError(null);
    setIsSubmittingEmail(true);
    setEmailJobStatus({ state: 'waiting', progress: 5, message: 'Submitting job to BullMQ distributed queue...' });

    try {
      const res = await fetch('/api/tutorial/email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repoPath: activeRepo, email: emailInput })
      });

      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || 'Failed to enqueue email job');
      }

      setEmailJobId(data.jobId);
      setEmailJobStatus({
        id: data.jobId,
        state: 'waiting',
        progress: 10,
        message: data.message || 'Queued in worker...',
        queueType: data.queueType
      });

      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = setInterval(async () => {
        try {
          const pollRes = await fetch(`/api/tutorial/email/status/${data.jobId}`);
          if (pollRes.ok) {
            const status = await pollRes.json();
            setEmailJobStatus(status);
            if (status.state === 'completed' || status.state === 'failed') {
              clearInterval(pollIntervalRef.current);
              setIsSubmittingEmail(false);
            }
          }
        } catch (pollErr) {
          console.warn('Status poll error:', pollErr.message);
        }
      }, 1500);

    } catch (err) {
      setEmailError(err.message);
      setIsSubmittingEmail(false);
      setEmailJobStatus(null);
    }
  };

  useEffect(() => {
    if (activeRepo) {
      loadCachedTutorial(activeRepo);
    }
  }, [activeRepo]);

  const loadCachedTutorial = async (repo) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/tutorial?path=${encodeURIComponent(repo)}`);
      if (res.ok) {
        const data = await res.json();
        setTutorial(data);
        setActiveChapterIndex(0);
      } else {
        setTutorial(null);
      }
    } catch (e) {
      console.warn('No cached tutorial found:', e.message);
      setTutorial(null);
    } finally {
      setLoading(false);
    }
  };

  const startTutorialGeneration = (forceRefresh = false) => {
    if (!activeRepo || isGenerating) return;

    setIsGenerating(true);
    setError(null);
    setGeneratingStep('Initializing architecture curriculum...');

    const incomingChapters = [];
    const refreshParam = forceRefresh ? '&refresh=true' : '';
    const eventSource = new EventSource(`/api/tutorial-stream?path=${encodeURIComponent(activeRepo)}${refreshParam}`);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.step === 'start' || data.step === 'chapter_start') {
          setGeneratingStep(data.message || `Generating ${data.title}...`);
        } else if (data.step === 'chapter_done') {
          incomingChapters.push(data.chapter);
          setTutorial(prev => ({
            repoPath: activeRepo,
            repoName: activeRepo.split(/[\/\\]/).pop(),
            chapters: [...incomingChapters]
          }));
          setActiveChapterIndex(incomingChapters.length - 1);
        } else if (data.step === 'complete') {
          setTutorial(data.tutorial);
          setIsGenerating(false);
          eventSource.close();
        } else if (data.step === 'cached') {
          setTutorial(data.tutorial);
          setIsGenerating(false);
          eventSource.close();
        } else if (data.step === 'error') {
          setError(data.error);
          setIsGenerating(false);
          eventSource.close();
        }
      } catch (err) {
        console.error('SSE Error:', err);
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      setIsGenerating(false);
    };
  };

  const handleExportMarkdown = async () => {
    if (!tutorial) return;

    try {
      const res = await fetch('/api/tutorial/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repoPath: activeRepo })
      });

      if (!res.ok) throw new Error('Export failed');

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${tutorial.repoName || 'architecture'}_blueprint.md`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      alert('Failed to export markdown: ' + err.message);
    }
  };

  const activeChapter = tutorial?.chapters?.[activeChapterIndex];

  return (
    <div style={{ maxWidth: '1180px', margin: '0 auto 32px auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Control Bar */}
      <div className="card" style={{ padding: '16px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <BookOpen size={18} style={{ color: 'var(--text-primary)' }} />
          <div>
            <div style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>
              Architecture Blueprint & Engineering Book
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              Autonomous deep-dive textbook with Mermaid topology, sequence flows, data ERDs, and security analysis.
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            className="btn btn-secondary"
            onClick={() => setShowEmailModal(true)}
            style={{ fontSize: '12.5px', display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <Mail size={14} />
            <span>Email PDF</span>
          </button>

          {tutorial && (
            <button
              className="btn btn-secondary"
              onClick={handleExportMarkdown}
              style={{ fontSize: '12.5px', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <Download size={14} />
              <span>Export Markdown</span>
            </button>
          )}

          <button
            className="btn btn-primary"
            onClick={() => startTutorialGeneration(!!tutorial)}
            disabled={isGenerating}
            style={{ fontSize: '12.5px', display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            {isGenerating ? (
              <>
                <RefreshCw size={14} className="spin" />
                <span>Generating Chapters...</span>
              </>
            ) : tutorial ? (
              <>
                <RefreshCw size={14} />
                <span>Regenerate (Fresh)</span>
              </>
            ) : (
              <>
                <Sparkles size={14} />
                <span>Generate Architecture Tutorial</span>
              </>
            )}
          </button>
        </div>
      </div>

      {isGenerating && (
        <div className="card" style={{ padding: '12px 18px', display: 'flex', alignItems: 'center', gap: '10px', fontSize: '13px', color: 'var(--text-secondary)' }}>
          <span className="status-dot warning" />
          <span>{generatingStep}</span>
        </div>
      )}

      {error && (
        <div style={{ padding: '12px 16px', backgroundColor: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: '6px', color: '#fca5a5', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* Main Reader View */}
      {tutorial && tutorial.chapters && tutorial.chapters.length > 0 ? (
        <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: '16px', alignItems: 'start' }}>
          {/* Left Sidebar Table of Contents */}
          <div className="card" style={{ padding: '16px 12px' }}>
            <div style={{ fontSize: '11.5px', fontWeight: '600', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', padding: '0 8px 10px 8px' }}>
              Curriculum Chapters ({tutorial.chapters.length})
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', maxHeight: 'calc(100vh - 220px)', overflowY: 'auto', paddingRight: '4px' }}>
              {tutorial.chapters.map((ch, idx) => {
                const isActive = idx === activeChapterIndex;
                return (
                  <button
                    key={ch.id || idx}
                    onClick={() => setActiveChapterIndex(idx)}
                    style={{
                      textAlign: 'left',
                      padding: '8px 10px',
                      borderRadius: '5px',
                      backgroundColor: isActive ? '#27272a' : 'transparent',
                      border: 'none',
                      color: isActive ? '#ffffff' : 'var(--text-secondary)',
                      fontSize: '12.5px',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    <CheckCircle2 size={13} style={{ color: isActive ? '#3b82f6' : 'var(--text-muted)', flexShrink: 0 }} />
                    <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {ch.title}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Reading Pane */}
          <div className="card" style={{ padding: '28px 32px', minHeight: '650px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
            <div>
              {activeChapter && (
                <>
                  <div style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '16px', marginBottom: '24px' }}>
                    <div style={{ fontSize: '12px', color: '#3b82f6', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                      Chapter {activeChapterIndex + 1} of {tutorial.chapters.length}
                    </div>
                    <h1 style={{ fontSize: '20px', fontWeight: '700', color: '#ffffff', margin: '6px 0 4px 0' }}>
                      {activeChapter.title}
                    </h1>
                    <p style={{ fontSize: '13.5px', color: 'var(--text-secondary)', margin: 0 }}>
                      {activeChapter.subtitle}
                    </p>
                  </div>

                  {/* Rendered Chapter Body */}
                  <ChapterRenderer chapter={activeChapter} />
                </>
              )}
            </div>

            {/* Pagination Controls */}
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              paddingTop: '24px',
              marginTop: '40px',
              borderTop: '1px solid var(--border-color)'
            }}>
              <button
                className="btn btn-secondary"
                disabled={activeChapterIndex === 0}
                onClick={() => setActiveChapterIndex(prev => Math.max(0, prev - 1))}
                style={{ fontSize: '12.5px', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <ChevronLeft size={15} />
                <span>Previous</span>
              </button>

              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Chapter {activeChapterIndex + 1} / {tutorial.chapters.length}
              </span>

              <button
                className="btn btn-secondary"
                disabled={activeChapterIndex >= tutorial.chapters.length - 1}
                onClick={() => setActiveChapterIndex(prev => Math.min(tutorial.chapters.length - 1, prev + 1))}
                style={{ fontSize: '12.5px', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <span>Next</span>
                <ChevronRight size={15} />
              </button>
            </div>
          </div>
        </div>
      ) : (
        /* Empty State */
        <div className="card" style={{ padding: '60px 20px', textAlign: 'center' }}>
          <BookOpen size={36} style={{ color: 'var(--text-muted)', margin: '0 auto 12px auto' }} />
          <h3 style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text-primary)', marginBottom: '6px' }}>
            No Architecture Blueprint Generated Yet
          </h3>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', maxWidth: '540px', margin: '0 auto 20px auto' }}>
            Click <strong>Generate Architecture Tutorial</strong> above to autonomously compile an exhaustive 10-chapter engineering textbook with 20+ Mermaid diagrams for <strong>{activeRepo?.split(/[\/\\]/).pop()}</strong>.
          </p>
          <button
            className="btn btn-primary"
            onClick={startTutorialGeneration}
            disabled={isGenerating}
            style={{ fontSize: '13px', padding: '8px 18px' }}
          >
            <Sparkles size={15} style={{ marginRight: '6px' }} />
            <span>Generate Architecture Tutorial</span>
          </button>
        </div>
      )}

      {/* Email PDF Modal with BullMQ Queue Tracking */}
      {showEmailModal && (
        <div style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.75)',
          backdropFilter: 'blur(5px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999,
          padding: '16px'
        }}>
          <div className="card" style={{
            width: '100%',
            maxWidth: '520px',
            backgroundColor: '#141417',
            border: '1px solid #27272a',
            borderRadius: '12px',
            boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5)',
            overflow: 'hidden'
          }}>
            {/* Modal Header */}
            <div style={{
              padding: '18px 24px',
              borderBottom: '1px solid #27272a',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div style={{ width: '32px', height: '32px', borderRadius: '8px', backgroundColor: 'rgba(59, 130, 246, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#3b82f6' }}>
                  <Mail size={16} />
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '600', color: '#f4f4f5' }}>
                    Send Architecture Blueprint to Your Email
                  </h3>
                  <div style={{ fontSize: '11px', color: '#a1a1aa', marginTop: '1px' }}>
                    High-concurrency BullMQ worker queue delivery
                  </div>
                </div>
              </div>
              <button
                onClick={() => {
                  setShowEmailModal(false);
                  if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
                }}
                style={{
                  background: 'none',
                  border: 'none',
                  color: '#71717a',
                  cursor: 'pointer',
                  padding: '4px',
                  borderRadius: '4px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
              >
                <X size={18} />
              </button>
            </div>

            {/* Modal Body */}
            <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '18px' }}>
              <div style={{ fontSize: '12.5px', color: '#a1a1aa', lineHeight: '1.5' }}>
                Please enter your email address. RepoSage will compile the complete 10-chapter engineering textbook (including C4 system topologies, server lifecycles, request sequence flows, database ERDs, background queues, security boundaries, and onboarding guide for <strong style={{ color: '#e4e4e7' }}>{tutorial?.repoName || activeRepo?.split(/[\/\\]/).pop() || 'this codebase'}</strong>) into a publication-grade PDF and dispatch it to your inbox.
              </div>

              {/* Form Input */}
              <form onSubmit={handleSendEmail} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '11.5px', fontWeight: '600', color: '#d4d4d8', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    Where should we send your PDF?
                  </label>
                  <input
                    type="email"
                    value={emailInput}
                    onChange={(e) => setEmailInput(e.target.value)}
                    placeholder="Enter your email address (e.g. user@gmail.com)"
                    disabled={isSubmittingEmail}
                    autoFocus
                    required
                    style={{
                      width: '100%',
                      padding: '11px 14px',
                      backgroundColor: '#09090b',
                      border: '1px solid #3f3f46',
                      borderRadius: '6px',
                      color: '#f4f4f5',
                      fontSize: '13.5px',
                      outline: 'none',
                      transition: 'border-color 0.2s',
                      boxSizing: 'border-box'
                    }}
                  />
                </div>

                {emailError && (
                  <div style={{ padding: '10px 12px', backgroundColor: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: '6px', color: '#fca5a5', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <AlertCircle size={14} />
                    <span>{emailError}</span>
                  </div>
                )}

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '4px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: '#71717a' }}>
                    <span className="status-dot success" style={{ width: '6px', height: '6px' }} />
                    <span>Worker Queue Concurrency Active</span>
                  </div>

                  <button
                    type="submit"
                    disabled={isSubmittingEmail || !emailInput}
                    className="btn btn-primary"
                    style={{ fontSize: '13px', padding: '8px 18px', display: 'flex', alignItems: 'center', gap: '6px' }}
                  >
                    {isSubmittingEmail ? (
                      <>
                        <RefreshCw size={14} className="spin" />
                        <span>Processing in Queue...</span>
                      </>
                    ) : (
                      <>
                        <Send size={14} />
                        <span>Send Blueprint PDF</span>
                      </>
                    )}
                  </button>
                </div>
              </form>

              {/* Real-Time Job Status Tracker */}
              {emailJobStatus && (
                <div style={{
                  padding: '16px',
                  backgroundColor: '#0c0c0e',
                  border: '1px solid #27272a',
                  borderRadius: '8px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '10px'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{
                        fontSize: '10.5px',
                        fontWeight: '700',
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                        padding: '2px 8px',
                        borderRadius: '12px',
                        backgroundColor: emailJobStatus.state === 'completed' ? 'rgba(34, 197, 94, 0.15)' : emailJobStatus.state === 'failed' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(59, 130, 246, 0.15)',
                        color: emailJobStatus.state === 'completed' ? '#4ade80' : emailJobStatus.state === 'failed' ? '#f87171' : '#60a5fa'
                      }}>
                        {emailJobStatus.state === 'completed' ? 'Delivered' : emailJobStatus.state === 'failed' ? 'Failed' : 'Processing in Queue'}
                      </span>
                      <span style={{ fontSize: '11px', color: '#71717a' }}>
                        ID: {emailJobStatus.id?.slice(0, 16)}...
                      </span>
                    </div>

                    <span style={{ fontSize: '12px', fontWeight: '600', color: '#e4e4e7' }}>
                      {emailJobStatus.progress || 0}%
                    </span>
                  </div>

                  {/* Progress Bar */}
                  <div style={{ width: '100%', height: '6px', backgroundColor: '#27272a', borderRadius: '3px', overflow: 'hidden' }}>
                    <div style={{
                      width: `${emailJobStatus.progress || 0}%`,
                      height: '100%',
                      backgroundColor: emailJobStatus.state === 'completed' ? '#22c55e' : emailJobStatus.state === 'failed' ? '#ef4444' : '#3b82f6',
                      transition: 'width 0.4s ease'
                    }} />
                  </div>

                  {/* Status Message */}
                  <div style={{ fontSize: '12px', color: '#a1a1aa', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    {emailJobStatus.state === 'completed' ? (
                      <CheckCircle2 size={14} style={{ color: '#22c55e' }} />
                    ) : emailJobStatus.state === 'failed' ? (
                      <AlertCircle size={14} style={{ color: '#ef4444' }} />
                    ) : (
                      <RefreshCw size={13} className="spin" style={{ color: '#3b82f6' }} />
                    )}
                    <span>{emailJobStatus.message || 'Worker processing task...'}</span>
                  </div>

                  {/* Success Preview URL for Ethereal inbox if test account was used */}
                  {emailJobStatus.result?.previewUrl && (
                    <div style={{ marginTop: '6px', paddingTop: '10px', borderTop: '1px solid #27272a' }}>
                      <a
                        href={emailJobStatus.result.previewUrl}
                        target="_blank"
                        rel="noreferrer"
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                          fontSize: '12px',
                          color: '#60a5fa',
                          textDecoration: 'none',
                          fontWeight: '500'
                        }}
                      >
                        <span>📬 Open Delivered Email in Browser (Ethereal Preview)</span>
                        <ExternalLink size={12} />
                      </a>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Renders formatted chapter markdown with integrated Mermaid diagram component
 */
function ChapterRenderer({ chapter }) {
  const parts = splitMarkdownAndMermaid(chapter.content);

  return (
    <div style={{ lineHeight: '1.7', fontSize: '14px', color: 'var(--text-primary)' }}>
      {parts.map((part, index) => {
        if (part.type === 'mermaid') {
          return <MermaidViewer key={index} chartCode={part.code} id={`mermaid-${chapter.id}-${index}`} />;
        }
        return <FormattedMarkdownText key={index} text={part.text} />;
      })}
    </div>
  );
}

/**
 * Split text into regular markdown slices and mermaid code slices
 */
function splitMarkdownAndMermaid(content) {
  if (!content) return [];
  const regex = /```mermaid\s*([\s\S]*?)```/gi;
  const parts = [];
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'markdown', text: content.substring(lastIndex, match.index) });
    }
    parts.push({ type: 'mermaid', code: match[1].trim() });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < content.length) {
    parts.push({ type: 'markdown', text: content.substring(lastIndex) });
  }

  return parts;
}

/**
 * Dynamic Asynchronous Mermaid SVG Renderer with Pre-Validation and Safe Fallback
 */
function MermaidViewer({ chartCode, id }) {
  const containerRef = useRef(null);
  const [svgContent, setSvgContent] = useState('');
  const [renderError, setRenderError] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let isMounted = true;
    const cleanedCode = cleanMermaidCode(chartCode);

    const cleanDomArtifacts = (uid) => {
      if (uid) {
        const errorEl = document.getElementById(`d${uid}`);
        if (errorEl) errorEl.remove();
      }
      document.querySelectorAll('body > svg[id^="dmmd_"]').forEach(el => el.remove());
      document.querySelectorAll('body > [aria-roledescription="error"]').forEach(el => el.remove());
      document.querySelectorAll('body > [id^="dmmd_"]').forEach(el => el.remove());
    };

    const renderDiagram = async () => {
      const uniqueId = `mmd_${Math.random().toString(36).substring(2, 9)}`;

      try {
        setRenderError(null);
        // Pre-validate diagram syntax to prevent Mermaid from injecting DOM error bomb icons
        const isValid = await mermaid.parse(cleanedCode, { suppressErrors: true });
        if (!isValid) {
          cleanDomArtifacts(uniqueId);
          if (isMounted) setRenderError('Diagram format specification');
          return;
        }

        const { svg } = await mermaid.render(uniqueId, cleanedCode);
        if (isMounted) {
          setSvgContent(svg);
        }
      } catch (err) {
        cleanDomArtifacts(uniqueId);
        if (isMounted) {
          console.warn('[Mermaid Render Caught]:', err.message);
          setRenderError(err.message || 'Syntax parsing');
        }
      }
    };

    renderDiagram();

    return () => {
      isMounted = false;
      cleanDomArtifacts();
    };
  }, [chartCode]);

  return (
    <div style={{
      margin: '20px 0',
      backgroundColor: '#0c0c0e',
      border: '1px solid var(--border-color)',
      borderRadius: '8px',
      padding: '20px',
      overflowX: 'auto',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center'
    }}>
      <div style={{
        width: '100%',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '14px',
        paddingBottom: '8px',
        borderBottom: '1px solid rgba(255,255,255,0.06)'
      }}>
        <div style={{ fontSize: '11px', color: '#60a5fa', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Interactive Architectural Diagram
        </div>
        <button
          className="btn btn-secondary"
          onClick={() => {
            navigator.clipboard.writeText(cleanMermaidCode(chartCode));
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
          }}
          style={{ fontSize: '11px', padding: '3px 8px', display: 'flex', alignItems: 'center', gap: '4px' }}
        >
          {copied ? <Check size={12} style={{ color: '#22c55e' }} /> : <Copy size={12} />}
          <span>{copied ? 'Copied' : 'Copy Diagram'}</span>
        </button>
      </div>

      {renderError ? (
        <div style={{ width: '100%', backgroundColor: '#141417', border: '1px solid #27272a', borderRadius: '6px', padding: '14px' }}>
          <div style={{ fontSize: '11px', color: '#a1a1aa', marginBottom: '8px' }}>
            Architectural Topology Specification:
          </div>
          <pre style={{ margin: 0, padding: '12px', backgroundColor: '#09090b', borderRadius: '4px', fontSize: '12px', color: '#38bdf8', fontFamily: 'monospace', overflowX: 'auto' }}>
            <code>{cleanMermaidCode(chartCode)}</code>
          </pre>
        </div>
      ) : svgContent ? (
        <div
          ref={containerRef}
          dangerouslySetInnerHTML={{ __html: svgContent }}
          style={{ width: '100%', display: 'flex', justifyContent: 'center' }}
        />
      ) : (
        <div style={{ padding: '24px', fontSize: '12px', color: 'var(--text-muted)' }}>
          Rendering architecture diagram...
        </div>
      )}
    </div>
  );
}

/**
 * Lightweight Markdown HTML renderer for typography and styling
 */
function FormattedMarkdownText({ text }) {
  if (!text) return null;

  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Code blocks
  html = html.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (m, lang, code) => {
    return `<pre style="background-color: #0c0c0e; border: 1px solid var(--border-color); border-radius: 6px; padding: 12px; margin: 14px 0; overflow-x: auto; font-family: monospace; font-size: 12.5px; color: #e4e4e7;"><code>${code}</code></pre>`;
  });

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code style="background-color: #18181b; border: 1px solid var(--border-color); padding: 2px 6px; border-radius: 4px; font-family: monospace; font-size: 12px; color: #e4e4e7;">$1</code>');

  // Headers
  html = html.replace(/^### (.*?)$/gm, '<h3 style="font-size: 15px; font-weight: 600; color: #ffffff; margin: 20px 0 8px 0;">$1</h3>');
  html = html.replace(/^## (.*?)$/gm, '<h2 style="font-size: 17px; font-weight: 600; color: #ffffff; margin: 26px 0 10px 0; border-bottom: 1px solid var(--border-color); padding-bottom: 6px;">$1</h2>');
  html = html.replace(/^# (.*?)$/gm, '<h1 style="font-size: 20px; font-weight: 700; color: #ffffff; margin: 28px 0 12px 0;">$1</h1>');

  // Bold & Italic
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong style="color: #ffffff;">$1</strong>');
  html = html.replace(/\*(.*?)\*/g, '<em style="color: #d4d4d8;">$1</em>');

  // Lists
  html = html.replace(/^\* (.*?)$/gm, '<li style="margin: 4px 0 4px 18px; color: var(--text-primary);">$1</li>');
  html = html.replace(/^- (.*?)$/gm, '<li style="margin: 4px 0 4px 18px; color: var(--text-primary);">$1</li>');

  // Paragraphs
  html = html.replace(/\n\n/g, '<div style="margin-bottom: 12px;"></div>');

  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}
