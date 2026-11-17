import React from 'react';
import { Layers } from 'lucide-react';
export default function Header({ health, activeRepo }) {
 const cacheConnected=health?.services?.cache?.connected;
 const chromaConnected=health?.services?.chroma?.connected;
 const llmConfigured=health?.services?.llm?.configured;
 return <header className="app-header">
 <a href="/" className="header-brand"><span className="brand-mark" aria-hidden="true"><Layers /></span>RepoSage</a>
 <div className="header-status-group">
 {activeRepo&&<span className="header-repo-pill" title={activeRepo}>{activeRepo.split(/[\/\\]/).pop()}</span>}
 <div className="header-status-item" title={chromaConnected?'Vector index connected':'Vector index unavailable'}><span className={`status-dot ${chromaConnected?'online':'offline'}`} /><span>Index</span></div>
 <div className="header-status-item" title={cacheConnected?'Cache connected':'Cache unavailable'}><span className={`status-dot ${cacheConnected?'online':'warning'}`} /><span>Cache</span></div>
 <div className="header-status-item" title={llmConfigured?'AI provider configured':'AI provider not configured'}><span className={`status-dot ${llmConfigured?'online':'warning'}`} /><span>{health?.services?.llm?.provider==='openai'?'OpenAI':'Gemini'}</span></div>
 </div></header>;
}
