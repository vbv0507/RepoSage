import React from 'react';

export default function Header({ health, activeRepo }) {
  const redisConnected = health?.services?.redis?.connected;
  const chromaConnected = health?.services?.chroma?.connected;
  const llmConfigured = health?.services?.llm?.configured;

  return (
    <header style={{
      borderBottom: '1px solid var(--border-color)',
      backgroundColor: '#0c0c0e',
      padding: '12px 24px',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <span style={{ fontSize: '15px', fontWeight: '600', color: '#ffffff', letterSpacing: '-0.01em' }}>
          RepoSage
        </span>
        <span style={{ color: 'var(--border-color)', userSelect: 'none' }}>/</span>
        <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
          Codebase Architecture Copilot
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        {activeRepo && (
          <span style={{
            fontSize: '12px',
            color: 'var(--text-muted)',
            fontFamily: 'monospace',
            backgroundColor: '#18181b',
            padding: '3px 8px',
            borderRadius: '4px',
            border: '1px solid var(--border-color)'
          }}>
            {activeRepo.split(/[\/\\]/).pop()}
          </span>
        )}

        {/* ChromaDB Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-secondary)' }}>
          <span className={`status-dot ${chromaConnected ? 'online' : 'offline'}`} />
          <span>{chromaConnected ? 'ChromaDB' : 'Chroma Offline'}</span>
        </div>

        {/* Redis Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-secondary)' }}>
          <span className={`status-dot ${redisConnected ? 'online' : 'warning'}`} />
          <span>{redisConnected ? 'Redis' : 'Cache (Memory)'}</span>
        </div>

        {/* LLM Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-secondary)' }}>
          <span className={`status-dot ${llmConfigured ? 'online' : 'warning'}`} />
          <span>{health?.services?.llm?.provider === 'gemini' ? 'Gemini 1.5' : 'OpenAI'}</span>
        </div>
      </div>
    </header>
  );
}
