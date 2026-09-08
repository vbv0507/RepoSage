import React, { useState } from 'react';

export default function RepoIngestion({ onIngestionComplete, activeRepo }) {
  const [repoPath, setRepoPath] = useState(activeRepo || 'd:/new/ai_agent/RAG/project-1-chrome-extension');
  const [isIngesting, setIsIngesting] = useState(false);
  const [currentStep, setCurrentStep] = useState('');
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);

  const startIngestion = () => {
    if (!repoPath) return;

    setIsIngesting(true);
    setError(null);
    setStats(null);
    setCurrentStep('Connecting to codebase...');

    const eventSource = new EventSource(`/api/ingest-stream?path=${encodeURIComponent(repoPath)}`);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.message) {
          setCurrentStep(data.message);
        } else if (data.step === 'parsing_progress') {
          setCurrentStep(`Parsing files (${data.current}/${data.total})...`);
        } else if (data.step === 'finished') {
          setCurrentStep('Analysis complete.');
          setStats(data.stats);
          eventSource.close();
          setIsIngesting(false);
          if (onIngestionComplete) onIngestionComplete(repoPath, data.stats);
        } else if (data.step === 'error') {
          setError(data.error);
          setIsIngesting(false);
          eventSource.close();
        }
      } catch (e) {
        console.error('SSE Error:', e);
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      setIsIngesting(false);
    };
  };

  return (
    <div className="card" style={{ padding: '20px', margin: '20px auto', maxWidth: '1100px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '14px' }}>
        <div>
          <h2 style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)' }}>
            Codebase Ingestion
          </h2>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Enter a local folder path or paste any public <strong>GitHub URL</strong>.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '6px' }}>
          <button
            className="btn btn-secondary"
            onClick={() => setRepoPath('d:/new/ai_agent/RAG/project-1-chrome-extension')}
            style={{ fontSize: '11.5px', padding: '3px 8px' }}
          >
            Current Repo
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => setRepoPath('https://github.com/expressjs/express')}
            style={{ fontSize: '11.5px', padding: '3px 8px' }}
          >
            expressjs/express
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '8px' }}>
        <input
          type="text"
          value={repoPath}
          onChange={(e) => setRepoPath(e.target.value)}
          placeholder="e.g. https://github.com/expressjs/express or D:/projects/my-app"
          disabled={isIngesting}
          style={{
            flex: 1,
            backgroundColor: 'var(--bg-input)',
            border: '1px solid var(--border-color)',
            borderRadius: '6px',
            padding: '9px 12px',
            color: 'var(--text-primary)',
            fontSize: '13px',
            fontFamily: 'monospace',
            outline: 'none'
          }}
        />
        <button
          className="btn btn-primary"
          onClick={startIngestion}
          disabled={isIngesting || !repoPath}
        >
          {isIngesting ? 'Analyzing...' : 'Analyze'}
        </button>
      </div>

      {isIngesting && (
        <div style={{ marginTop: '12px', fontSize: '12.5px', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="status-dot warning" />
          <span>{currentStep}</span>
        </div>
      )}

      {error && (
        <div style={{ marginTop: '12px', padding: '8px 12px', backgroundColor: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: '6px', color: '#fca5a5', fontSize: '12.5px' }}>
          {error}
        </div>
      )}

      {stats && (
        <div style={{
          marginTop: '16px',
          paddingTop: '16px',
          borderTop: '1px solid var(--border-color)',
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: '12px'
        }}>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Files</div>
            <div style={{ fontSize: '18px', fontWeight: '600', color: 'var(--text-primary)', marginTop: '2px' }}>
              {stats.filesCount}
            </div>
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>AST Blocks</div>
            <div style={{ fontSize: '18px', fontWeight: '600', color: 'var(--text-primary)', marginTop: '2px' }}>
              {stats.chunksCount}
            </div>
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Git Diffs</div>
            <div style={{ fontSize: '18px', fontWeight: '600', color: 'var(--text-primary)', marginTop: '2px' }}>
              {stats.gitDiffsCount}
            </div>
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Dependencies</div>
            <div style={{ fontSize: '18px', fontWeight: '600', color: 'var(--text-primary)', marginTop: '2px' }}>
              {stats.graphLinksCount}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
