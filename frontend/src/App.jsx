import React, { useState, useEffect, useRef } from 'react';
import Header from './components/Header';
import RepoIngestion from './components/RepoIngestion';
import ArchitectureGraph from './components/ArchitectureGraph';
import ChatCopilot from './components/ChatCopilot';
import { API_BASE } from './config';
import { MessageSquare, Network, GitBranch } from 'lucide-react';

export default function App() {
 const [health,setHealth]=useState(null);
 const [backendReady,setBackendReady]=useState(false);
 const [activeRepo,setActiveRepo]=useState('https://github.com/vbv0507/RepoSage');
 const [activeTab,setActiveTab]=useState('chat');
 // Preserve the existing 3-miss failure threshold and fast/steady health polling.
 const failStreakRef=useRef(0);
 const STREAK_THRESHOLD=3;
 const intervalRef=useRef(null);
 const backendReadyRef=useRef(false);
 const inFlightRef=useRef(false);
 const startPolling=(cadenceMs)=>{if(intervalRef.current)clearInterval(intervalRef.current);intervalRef.current=setInterval(fetchHealth,cadenceMs);};
 useEffect(()=>{fetchHealth();startPolling(8000);return()=>{if(intervalRef.current)clearInterval(intervalRef.current);};},[]);
 const fetchHealth=async()=>{
 if(inFlightRef.current)return;
 inFlightRef.current=true;
 try{
 const res=await fetch(`${API_BASE}/api/health`,{signal:AbortSignal.timeout(20000)});
 if(res.ok){const data=await res.json();failStreakRef.current=0;setHealth(data);if(!backendReadyRef.current){backendReadyRef.current=true;setBackendReady(true);startPolling(30000);}}
 else{failStreakRef.current=0;backendReadyRef.current=false;setBackendReady(false);startPolling(8000);}
 }catch(e){failStreakRef.current+=1;console.warn(`Backend poll failed (streak ${failStreakRef.current}/${STREAK_THRESHOLD}):`,e.message);if(failStreakRef.current>=STREAK_THRESHOLD&&backendReadyRef.current){backendReadyRef.current=false;setBackendReady(false);startPolling(8000);}}
 finally{inFlightRef.current=false;}
 };
 const handleIngestionComplete=(repoPath)=>{setActiveRepo(repoPath);fetchHealth();};
 return <div className="app-shell">
 <Header health={health} activeRepo={activeRepo}/>
 <main className="app-container">
 <section className="workspace-intro"><div><h1>RepoSage</h1><p>Your codebase, in context.</p></div><span className="workspace-label"><GitBranch aria-hidden="true"/>Architecture workspace</span></section>
 <RepoIngestion activeRepo={activeRepo} onIngestionComplete={handleIngestionComplete} backendReady={backendReady}/>
 <div className="tab-bar-container" role="tablist" aria-label="Workspace views">
 <button id="chat-tab" role="tab" aria-selected={activeTab==='chat'} aria-controls="chat-panel" onClick={()=>setActiveTab('chat')} className="btn tab-btn"><MessageSquare aria-hidden="true"/>Copilot Chat</button>
 <button id="graph-tab" role="tab" aria-selected={activeTab==='graph'} aria-controls="graph-panel" onClick={()=>setActiveTab('graph')} className="btn tab-btn"><Network aria-hidden="true"/>Module Dependencies</button>
 </div>
 {/* Keep both views mounted so chat and graph state survive tab switches. */}
 <div id="chat-panel" role="tabpanel" aria-labelledby="chat-tab" className="workspace-panel" hidden={activeTab!=='chat'}><ChatCopilot activeRepo={activeRepo}/></div>
 <div id="graph-panel" role="tabpanel" aria-labelledby="graph-tab" className="workspace-panel" hidden={activeTab!=='graph'}><ArchitectureGraph activeRepo={activeRepo}/></div>
 <footer className="workspace-footer"><span>RepoSage</span><span>Code · Architecture · Context</span></footer>
 </main></div>;
}
