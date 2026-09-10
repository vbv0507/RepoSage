import React, { useState } from 'react';
import { API_BASE } from '../config';

export default function ChatCopilot({ activeRepo }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: "Hello. I've indexed this codebase's AST structures and Git archaeology diffs. Ask any questions about how the architecture works or why specific decisions were made.",
      codeCitations: [],
      gitCitations: []
    }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const suggestedPrompts = [
    "Explain the end-to-end data flow of this codebase.",
    "Why does this project use both ChromaDB and Redis together?",
    "What modules will be affected if we modify astParser.js?",
    "Show me architectural decisions revealed by Git Archaeology."
  ];

  const handleSend = async (questionText, forceRefresh = false) => {
    const q = questionText || input;
    if (!q.trim() || loading) return;

    setInput('');
    const userMsg = { role: 'user', text: q };
    setMessages(prev => [...prev, userMsg]);
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repoPath: activeRepo,
          question: q,
          refresh: Boolean(forceRefresh)
        })
      });

      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}`);
      }

      const data = await res.json();
      setMessages(prev => [...prev, {
        role: 'assistant',
        text: data.answer,
        codeCitations: data.codeCitations || [],
        gitCitations: data.gitCitations || [],
        fromCache: data.fromCache,
        semanticCache: data.semanticCache,
        cacheType: data.cacheType,
        matchedQuestion: data.matchedQuestion,
        similarity: data.similarity,
        offlineFallback: data.offlineFallback,
        offlineNoConfidentAnswer: data.offlineNoConfidentAnswer
      }]);
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        text: `Error querying codebase: ${err.message}. Please ensure the backend and vector DB are active.`,
        codeCitations: [],
        gitCitations: []
      }]);
    } finally {
      setLoading(false);
    }
  };

  const formatText = (txt) => {
    if (!txt) return '';
    let formatted = txt
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Code blocks ```lang ... ```
    formatted = formatted.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
      return `<pre style="background-color: #0c0c0e; border: 1px solid var(--border-color); border-radius: 6px; padding: 12px; margin: 10px 0; overflow-x: auto; font-family: monospace; font-size: 12.5px; color: #e4e4e7;"><code>${code}</code></pre>`;
    });

    // Headers
    formatted = formatted.replace(/^### (.*?)$/gm, '<h4 style="font-size: 14px; font-weight: 600; color: #ffffff; margin: 14px 0 6px 0;">$1</h4>');
    formatted = formatted.replace(/^## (.*?)$/gm, '<h3 style="font-size: 15px; font-weight: 600; color: #ffffff; margin: 16px 0 8px 0; border-bottom: 1px solid var(--border-color); padding-bottom: 4px;">$1</h3>');
    formatted = formatted.replace(/^# (.*?)$/gm, '<h2 style="font-size: 16px; font-weight: 700; color: #ffffff; margin: 18px 0 10px 0;">$1</h2>');

    // Bold & Italic
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong style="color: #ffffff;">$1</strong>');
    formatted = formatted.replace(/\*(.*?)\*/g, '<em style="color: #d4d4d8;">$1</em>');

    // Inline code
    formatted = formatted.replace(/`([^`]+)`/g, '<code style="background-color: #27272a; padding: 2px 5px; border-radius: 4px; font-size: 12px; color: #93c5fd;">$1</code>');

    // Bullet lists
    formatted = formatted.replace(/(?:^|\n)[*-] (.*?)(?=(?:\n|$))/g, '<li style="margin-left: 18px; margin-top: 4px;">$1</li>');

    // Ordered lists
    formatted = formatted.replace(/(?:^|\n)(\d+)\. (.*?)(?=(?:\n|$))/g, '<li style="margin-left: 18px; margin-top: 4px;"><strong>$1.</strong> $2</li>');

    // Horizontal rules
    formatted = formatted.replace(/^---$/gm, '<hr style="border: 0; border-top: 1px solid var(--border-color); margin: 14px 0;" />');

    // Newlines
    formatted = formatted.replace(/\n\n/g, '<br><br>').replace(/\n/g, '<br>');
    return formatted;
  };

  return (
    <div className="card chat-container">
      {/* Header & Quick Prompts */}
      <div style={{ borderBottom: '1px solid var(--border-color)' }}>
        <div style={{ padding: '12px 16px 8px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '6px' }}>
          <span style={{ fontSize: '14px', fontWeight: '600' }}>Copilot Chat</span>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>AST + Git Archaeology Grounded</span>
        </div>

        <div className="chat-prompts-bar">
          {suggestedPrompts.map((p, i) => (
            <button
              key={i}
              onClick={() => handleSend(p)}
              disabled={loading}
              className="btn btn-secondary chat-prompt-pill"
              style={{ fontSize: '11.5px', padding: '4px 10px' }}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Messages */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px'
      }}>
        {messages.map((msg, index) => (
          <div
            key={index}
            style={{
              alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
              maxWidth: msg.role === 'user' ? '80%' : '88%'
            }}
          >
            <div style={{
              backgroundColor: msg.role === 'user' ? '#27272a' : '#18181b',
              border: '1px solid var(--border-color)',
              borderRadius: '6px',
              padding: '12px 16px',
              fontSize: '13.5px',
              color: 'var(--text-primary)',
              lineHeight: 1.6
            }}>
              {msg.fromCache && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', flexWrap: 'wrap' }}>
                  {msg.semanticCache ? (
                    <span style={{
                      fontSize: '11px',
                      backgroundColor: msg.offlineFallback ? 'rgba(245, 158, 11, 0.15)' : 'rgba(59, 130, 246, 0.15)',
                      border: `1px solid ${msg.offlineFallback ? 'rgba(245, 158, 11, 0.35)' : 'rgba(59, 130, 246, 0.35)'}`,
                      color: msg.offlineFallback ? '#fbbf24' : '#60a5fa',
                      padding: '2px 8px',
                      borderRadius: '12px',
                      fontWeight: '500',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}>
                      ⚡ Close semantic cache match {msg.similarity ? `(${Math.round(msg.similarity * 100)}% match)` : ''}
                      {msg.matchedQuestion && <span style={{ opacity: 0.85 }}>• Similar to: "{msg.matchedQuestion}"</span>}
                    </span>
                  ) : (
                    <span style={{
                      fontSize: '11px',
                      backgroundColor: 'rgba(34, 197, 94, 0.15)',
                      border: '1px solid rgba(34, 197, 94, 0.3)',
                      color: '#4ade80',
                      padding: '2px 8px',
                      borderRadius: '12px',
                      fontWeight: '500'
                    }}>
                      ⚡ Exact Cache Hit (Redis)
                    </span>
                  )}
                </div>
              )}

              {msg.offlineNoConfidentAnswer && (
                <div style={{ marginBottom: '10px', padding: '10px', border: '1px solid rgba(245, 158, 11, 0.5)', borderRadius: '5px', backgroundColor: 'rgba(245, 158, 11, 0.12)', color: '#fbbf24', fontWeight: '600' }}>
                  No low-confidence cache answer was used.
                </div>
              )}

              <div dangerouslySetInnerHTML={{ __html: formatText(msg.text) }} />

              {/* Code Citations */}
              {msg.codeCitations && msg.codeCitations.length > 0 && (
                <div style={{ marginTop: '12px', paddingTop: '10px', borderTop: '1px solid var(--border-color)' }}>
                  <div style={{ fontSize: '11.5px', fontWeight: '600', color: 'var(--text-secondary)', marginBottom: '6px' }}>
                    Referenced Code ({msg.codeCitations.length}):
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {msg.codeCitations.map((c, ci) => (
                      <div key={ci} style={{ backgroundColor: '#121215', padding: '6px 10px', borderRadius: '4px', border: '1px solid var(--border-color)', fontSize: '12px', fontFamily: 'monospace', color: 'var(--text-secondary)' }}>
                        📄 {c.filePath} <span style={{ color: 'var(--text-muted)' }}>(L{c.startLine}-{c.endLine})</span>
                        {c.name && <span style={{ color: '#a1a1aa', marginLeft: '6px' }}>• {c.name}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Git Archaeology Citations */}
              {msg.gitCitations && msg.gitCitations.length > 0 && (
                <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid var(--border-color)' }}>
                  <div style={{ fontSize: '11.5px', fontWeight: '600', color: 'var(--text-secondary)', marginBottom: '6px' }}>
                    Git Archaeology (Why this was changed):
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {msg.gitCitations.map((g, gi) => (
                      <div key={gi} style={{ backgroundColor: '#121215', padding: '6px 10px', borderRadius: '4px', border: '1px solid var(--border-color)', fontSize: '12px', color: 'var(--text-secondary)' }}>
                        <span style={{ fontFamily: 'monospace', color: 'var(--text-muted)' }}>commit {g.hash}</span>: "{g.summary}"
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div style={{ alignSelf: 'flex-start', color: 'var(--text-muted)', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span className="status-dot warning" />
            <span>Analyzing codebase vectors...</span>
          </div>
        )}
      </div>

      {/* Input */}
      <div style={{ padding: '12px 20px', borderTop: '1px solid var(--border-color)', display: 'flex', gap: '8px' }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Ask about architecture, dependencies, or decisions..."
          disabled={loading}
          style={{
            flex: 1,
            backgroundColor: 'var(--bg-input)',
            border: '1px solid var(--border-color)',
            borderRadius: '6px',
            padding: '9px 12px',
            color: 'var(--text-primary)',
            fontSize: '13px',
            outline: 'none'
          }}
        />
        <button
          className="btn btn-primary"
          onClick={() => handleSend()}
          disabled={loading || !input.trim()}
        >
          Send
        </button>
      </div>
    </div>
  );
}
