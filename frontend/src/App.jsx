import React, { useState, useEffect } from 'react';
import Header from './components/Header';
import RepoIngestion from './components/RepoIngestion';
import ArchitectureGraph from './components/ArchitectureGraph';
import ChatCopilot from './components/ChatCopilot';
import CodeTutorial from './components/CodeTutorial';
import { API_BASE } from './config';

export default function App() {
  const [health, setHealth] = useState(null);
  const [activeRepo, setActiveRepo] = useState('d:/new/ai_agent/RAG/project-1-chrome-extension');
  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'graph' | 'tutorial'

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 8000);
    return () => clearInterval(interval);
  }, []);

  const fetchHealth = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/health`);
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

      <main className="app-container" style={{ flex: 1, padding: '0 16px' }}>
        <RepoIngestion
          activeRepo={activeRepo}
          onIngestionComplete={handleIngestionComplete}
        />

        {/* Responsive Tab Switcher */}
        <div className="tab-bar-container">
          <button
            onClick={() => setActiveTab('chat')}
            className={`btn tab-btn`}
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
            className={`btn tab-btn`}
            style={{
              backgroundColor: activeTab === 'graph' ? '#27272a' : 'transparent',
              color: activeTab === 'graph' ? 'var(--text-primary)' : 'var(--text-muted)',
              fontSize: '13px'
            }}
          >
            Module Dependencies
          </button>

          <button
            onClick={() => setActiveTab('tutorial')}
            className={`btn tab-btn`}
            style={{
              backgroundColor: activeTab === 'tutorial' ? '#27272a' : 'transparent',
              color: activeTab === 'tutorial' ? 'var(--text-primary)' : 'var(--text-muted)',
              fontSize: '13px'
            }}
          >
            Architecture Tutorial
          </button>
        </div>

        {/* Tab Content — always mounted, visibility toggled via CSS to preserve state across tab switches */}
        <div style={{ display: activeTab === 'chat' ? 'block' : 'none' }}>
          <ChatCopilot activeRepo={activeRepo} />
        </div>
        <div style={{ display: activeTab === 'graph' ? 'block' : 'none' }}>
          <ArchitectureGraph activeRepo={activeRepo} />
        </div>
        <div style={{ display: activeTab === 'tutorial' ? 'block' : 'none' }}>
          <CodeTutorial activeRepo={activeRepo} />
        </div>
      </main>
    </div>
  );
}
