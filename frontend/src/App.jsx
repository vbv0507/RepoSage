import React, { useState, useEffect } from 'react';
import Header from './components/Header';
import RepoIngestion from './components/RepoIngestion';
import ArchitectureGraph from './components/ArchitectureGraph';
import ChatCopilot from './components/ChatCopilot';

export default function App() {
  const [health, setHealth] = useState(null);
  const [activeRepo, setActiveRepo] = useState('d:/new/ai_agent/RAG/project-1-chrome-extension');
  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'graph'

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 8000);
    return () => clearInterval(interval);
  }, []);

  const fetchHealth = async () => {
    try {
      const res = await fetch('/api/health');
      if (res.ok) {
        const data = await res.json();
        setHealth(data);
      }
    } catch (e) {
      console.warn('Backend not responding yet');
    }
  };

  const handleIngestionComplete = (repoPath) => {
    setActiveRepo(repoPath);
    fetchHealth();
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Header health={health} activeRepo={activeRepo} />

      <main style={{ flex: 1, padding: '0 16px' }}>
        <RepoIngestion
          activeRepo={activeRepo}
          onIngestionComplete={handleIngestionComplete}
        />

        {/* Minimal Tab Switcher */}
        <div style={{
          maxWidth: '1100px',
          margin: '0 auto 16px auto',
          display: 'flex',
          gap: '4px',
          borderBottom: '1px solid var(--border-color)',
          paddingBottom: '8px'
        }}>
          <button
            onClick={() => setActiveTab('chat')}
            className="btn"
            style={{
              backgroundColor: activeTab === 'chat' ? '#27272a' : 'transparent',
              color: activeTab === 'chat' ? 'var(--text-primary)' : 'var(--text-muted)',
              fontSize: '13px'
            }}
          >
            Copilot Chat
          </button>

          <button
            onClick={() => setActiveTab('graph')}
            className="btn"
            style={{
              backgroundColor: activeTab === 'graph' ? '#27272a' : 'transparent',
              color: activeTab === 'graph' ? 'var(--text-primary)' : 'var(--text-muted)',
              fontSize: '13px'
            }}
          >
            Module Dependencies
          </button>
        </div>

        {/* Tab Content */}
        {activeTab === 'chat' ? (
          <ChatCopilot activeRepo={activeRepo} />
        ) : (
          <ArchitectureGraph activeRepo={activeRepo} />
        )}
      </main>
    </div>
  );
}
