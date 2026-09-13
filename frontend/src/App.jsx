import React, { useState, useEffect, useRef } from 'react';
import Header from './components/Header';
import RepoIngestion from './components/RepoIngestion';
import ArchitectureGraph from './components/ArchitectureGraph';
import ChatCopilot from './components/ChatCopilot';
import CodeTutorial from './components/CodeTutorial';
import { API_BASE } from './config';

export default function App() {
  const [health, setHealth] = useState(null);
  const [backendReady, setBackendReady] = useState(false);
  const [activeRepo, setActiveRepo] = useState('https://github.com/vbv0507/RepoSage');
  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'graph' | 'tutorial'

  // Consecutive-failure streak counter.
  // - Increments on each catch (timeout / network error).
  // - Resets to 0 on each successful response.
  // - Only flips backendReady back to false after STREAK_THRESHOLD consecutive
  //   failures, distinguishing a genuine idle scale-down (sustained silence) from
  //   a transient one-poll network blip.
  const failStreakRef = useRef(0);
  const STREAK_THRESHOLD = 3; // 3 misses × poll cadence ≈ 90s of silence

  // Poll cadence: fast (8s) while not ready so cold-start wake is detected quickly;
  // slow (30s) in steady-state to avoid hammering /api/health unnecessarily.
  // The interval ref lets us swap cadence without unmounting.
  const intervalRef = useRef(null);
  const backendReadyRef = useRef(false); // mirror for use inside interval callbacks

  const startPolling = (cadenceMs) => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    intervalRef.current = setInterval(fetchHealth, cadenceMs);
  };

  useEffect(() => {
    fetchHealth();
    startPolling(8000); // start fast until first success
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchHealth = async () => {
    try {
      // 8s per-request timeout: fail fast so the polling loop retries at cadence.
      const res = await fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(8000) });
      if (res.ok) {
        const data = await res.json();
        failStreakRef.current = 0; // reset streak on success
        setHealth(data);
        if (!backendReadyRef.current) {
          // First success (or recovery from scale-down): switch to slow steady-state poll.
          backendReadyRef.current = true;
          setBackendReady(true);
          startPolling(30000);
        }
      } else {
        // Real non-ok HTTP (e.g. 500) — backend reachable but unhealthy.
        failStreakRef.current = 0;
        backendReadyRef.current = false;
        setBackendReady(false);
        startPolling(8000); // poll fast to catch recovery
      }
    } catch (e) {
      // Network error or timeout — container may be cold or scaled to zero.
      failStreakRef.current += 1;
      console.warn(`Backend poll failed (streak ${failStreakRef.current}/${STREAK_THRESHOLD}):`, e.message);
      if (failStreakRef.current >= STREAK_THRESHOLD && backendReadyRef.current) {
        // Sustained failure after a previously confirmed-ready backend:
        // the container has almost certainly scaled back to zero. Show the
        // "waking up" state again and revert to fast polling.
        backendReadyRef.current = false;
        setBackendReady(false);
        startPolling(8000);
      }
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
          backendReady={backendReady}
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
