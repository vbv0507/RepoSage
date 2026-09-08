import React from 'react';

export default function Header({ health, activeRepo }) {
  const redisConnected = health?.services?.redis?.connected;
  const chromaConnected = health?.services?.chroma?.connected;
  const llmConfigured = health?.services?.llm?.configured;

  return (
    <header className="app-header">
      <div className="header-brand">
        <span style={{ fontSize: '15px', fontWeight: '600', color: '#ffffff', letterSpacing: '-0.01em', whiteSpace: 'nowrap' }}>
          RepoSage
        </span>
        <span className="header-slash" style={{ color: 'var(--border-color)', userSelect: 'none' }}>/</span>
        <span className="header-subtitle" style={{ fontSize: '13px', color: 'var(--text-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          Architecture Intelligence
        </span>
      </div>

      <div className="header-status-group">
        {activeRepo && (
          <span className="header-repo-pill" style={{
            fontSize: '11.5px',
            color: 'var(--text-muted)',
            fontFamily: 'monospace',
            backgroundColor: '#18181b',
            padding: '3px 8px',
            borderRadius: '4px',
            border: '1px solid var(--border-color)',
            maxWidth: '130px',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap'
          }}>
            {activeRepo.split(/[\/\\]/).pop()}
          </span>
        )}

        {/* ChromaDB Status */}
        <div className="header-status-item" style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', color: 'var(--text-secondary)' }}>
          <span className={`status-dot ${chromaConnected ? 'online' : 'offline'}`} />
          <span style={{ whiteSpace: 'nowrap' }}>{chromaConnected ? 'ChromaDB' : 'Chroma'}</span>
        </div>

        {/* Redis Status */}
        <div className="header-status-item" style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', color: 'var(--text-secondary)' }}>
          <span className={`status-dot ${redisConnected ? 'online' : 'warning'}`} />
          <span style={{ whiteSpace: 'nowrap' }}>{redisConnected ? 'Redis' : 'Cache'}</span>
        </div>

        {/* LLM Status */}
        <div className="header-status-item" style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', color: 'var(--text-secondary)' }}>
          <span className={`status-dot ${llmConfigured ? 'online' : 'warning'}`} />
          <span style={{ whiteSpace: 'nowrap' }}>{health?.services?.llm?.provider === 'gemini' ? 'Gemini 2.5' : 'OpenAI'}</span>
        </div>
      </div>
    </header>
  );
}
