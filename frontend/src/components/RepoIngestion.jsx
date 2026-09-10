import React, { useState, useEffect, useRef } from 'react';
import { API_BASE } from '../config';

export default function RepoIngestion({ onIngestionComplete, activeRepo }) {
  const [repoPath, setRepoPath] = useState(activeRepo || 'https://github.com/vbv0507/RepoSage');
  const [isIngesting, setIsIngesting] = useState(false);
  const [currentStep, setCurrentStep] = useState('');
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const folderInputRef = useRef(null);

  useEffect(() => {
    if (activeRepo) {
      setRepoPath(activeRepo);
    }
  }, [activeRepo]);

  const startIngestion = (force = false, pathOverride = repoPath) => {
    const requestedPath = pathOverride.trim();
    if (!requestedPath) return;

    setIsIngesting(true);
    setError(null);
    setStats(null);
    setCurrentStep('Connecting to codebase...');

    const forceParam = force ? '&force=true' : '';
    const eventSource = new EventSource(`${API_BASE}/api/ingest-stream?path=${encodeURIComponent(requestedPath)}${forceParam}`);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.step === 'cache_hit') {
          setCurrentStep(data.message);
        } else if (data.message) {
          setCurrentStep(data.message);
        } else if (data.step === 'parsing_progress') {
          setCurrentStep(`Parsing files (${data.current}/${data.total})...`);
        } else if (data.step === 'finished') {
          setCurrentStep(data.stats?.fromCache ? '⚡ Reused existing vector cache!' : 'Analysis complete.');
          setStats(data.stats);
          eventSource.close();
          setIsIngesting(false);
          if (onIngestionComplete) onIngestionComplete(requestedPath, data.stats);
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
      setError((previous) => previous || 'The analysis connection closed unexpectedly. Ensure the backend is running and try again.');
      eventSource.close();
      setIsIngesting(false);
    };
  };

  const uploadFolder = async (event) => {
    const selectedFiles = Array.from(event.target.files || []);
    event.target.value = '';
    if (!selectedFiles.length) return;

    setIsIngesting(true);
    setError(null);
    setStats(null);
    setCurrentStep(`Uploading ${selectedFiles.length} files from your selected folder...`);

    try {
      const formData = new FormData();
      selectedFiles.forEach((file) => {
        formData.append('files', file, file.webkitRelativePath || file.name);
      });
      const response = await fetch(`${API_BASE}/api/upload-repository`, { method: 'POST', body: formData });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Folder upload failed.');

      setRepoPath(data.repoPath);
      setIsIngesting(false);
      startIngestion(false, data.repoPath);
    } catch (uploadError) {
      setError(uploadError.message || 'Folder upload failed.');
      setIsIngesting(false);
    }
  };

  return (
    <div className="card ingestion-card">
      <div className="ingestion-header">
        <div>
          <h2 style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)' }}>
            Codebase Ingestion
          </h2>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Paste a public <strong>GitHub URL</strong>, or enter a local folder mounted for the backend.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          <button
            className="btn btn-secondary"
            onClick={() => setRepoPath('https://github.com/vbv0507/RepoSage')}
            style={{ fontSize: '11.5px', padding: '3px 8px' }}
          >
            RepoSage
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => setRepoPath('https://github.com/expressjs/express')}
            style={{ fontSize: '11.5px', padding: '3px 8px' }}
          >
            expressjs/express
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => folderInputRef.current?.click()}
            disabled={isIngesting}
            style={{ fontSize: '11.5px', padding: '3px 8px' }}
          >
            Upload folder
          </button>
          <input
            ref={folderInputRef}
            type="file"
            webkitdirectory=""
            directory=""
            multiple
            onChange={uploadFolder}
            style={{ display: 'none' }}
          />
        </div>
      </div>

      <div className="ingestion-input-row">
        <input
          type="text"
          className="ingestion-input"
          value={repoPath}
          onChange={(e) => setRepoPath(e.target.value)}
          placeholder="e.g. https://github.com/vbv0507/RepoSage"
          disabled={isIngesting}
        />
        <button
          className="btn btn-primary"
          onClick={() => startIngestion(false)}
          disabled={isIngesting || !repoPath}
          style={{ flexShrink: 0 }}
        >
          {isIngesting ? 'Analyzing...' : 'Analyze'}
        </button>
        {stats && (
          <button
            className="btn btn-secondary"
            onClick={() => startIngestion(true)}
            disabled={isIngesting || !repoPath}
            title="Force re-compute all embeddings from scratch"
            style={{ fontSize: '12px', padding: '7px 10px', flexShrink: 0 }}
          >
            Re-index
          </button>
        )}
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

      <p style={{ marginTop: '8px', fontSize: '11.5px', color: 'var(--text-muted)' }}>
        On this hosted app, use <strong>Upload folder</strong> for a local project (source files only, 25 MB max), or paste a public GitHub URL.
      </p>

      {stats && (
        <>
          <div className="stats-grid">
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
          {stats.fromCache && (
            <div style={{ marginTop: '10px', fontSize: '11.5px', color: 'var(--success-color)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>⚡ Reused existing vector embeddings from ChromaDB (Instant load, zero re-embedding).</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}
