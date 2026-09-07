# 🧠 RepoSage - AI Architectural & Legacy Codebase Intelligence Copilot

> An advanced developer copilot that decodes legacy codebases, hidden architectural decisions, and cross-file dependencies—**even when developers committed with lazy messages like `"fix"`, `"wip"`, or `"update"`**.

---

## 🌟 Why RepoSage?

In real engineering teams, commit messages are often useless:
```text
- "fix"
- "wip"
- "changes"
- "asdf"
```
Standard RAG tools fail because they only index raw text or trust commit messages. **RepoSage** solves this with a **4-Layer Code Archaeology & AST Intelligence Pipeline**:

1. **"Diff-to-Intent" Git Archaeology**: Bypasses vague commit messages by passing actual `git diff` changesets to an LLM to synthesize objective architectural reasons behind code changes.
2. **AST Function & Class Chunking**: Chunks code by logical blocks (functions, classes, endpoints, schemas) rather than arbitrary line counts.
3. **Cross-File Dependency Call Graph**: Extracts imports and exports to build an interactive map showing how API routes, services, and data models connect.
4. **Dual Vector Store (ChromaDB)**: Simultaneously queries active code implementations AND historical Git diff changesets.
5. **High-Speed Redis Cache Layer**: Caches dependency call graphs and frequent developer queries for sub-millisecond responses (with zero-crash in-memory fallback).

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 Frontend Dashboard (React + Vite)           │
│                                                             │
│   ├── Repository Ingestion & Real-Time SSE Log Stream       │
│   ├── Architecture Dependency Map (Visual Module Explorer)  │
│   └── Copilot Chat (Code Blocks, Citations & Diff Traces)   │
└──────────────────────────────┬──────────────────────────────┘
                               │ REST / SSE (Port 5000)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 RepoSage Backend (Node.js Express)          │
│                                                             │
│   [ Ingestion & Analysis Engine ]                           │
│     ├── AST Parser (Functions, Classes, Imports)            │
│     ├── Git Archaeology Engine (Diff-to-Intent Synthesizer) │
│     └── Dependency Graph Builder                            │
│                                                             │
│   [ LangChain Multi-Vector RAG Engine ]                     │
│     ├── Code Definitions Retriever                          │
│     ├── Historical Git Changeset Retriever                  │
│     └── Architectural Synthesis Chain (Gemini / OpenAI)     │
└───────────────┬─────────────────────────────┬───────────────┘
                │ High-Speed Cache            │ Vector Embeddings
                ▼                             ▼
┌───────────────────────────────┐ ┌───────────────────────────┐
│       Redis (Port 6379)       │ │    ChromaDB (Port 8000)   │
│   - Dependency Call Graphs    │ │   - "reposage_code"       │
│   - Sub-ms Query Response     │ │   - "reposage_diffs"      │
└───────────────────────────────┘ └───────────────────────────┘
```

---

## 🚀 Quickstart Guide

### Option 1: Run with Docker Compose (Recommended)

To run the entire multi-service stack (Redis + ChromaDB + Backend + Frontend) in one command:

```bash
# In the project root directory:
docker compose up -d
```
Then open **`http://localhost:3000`** in your browser!

---

### Option 2: Run Locally on Windows (Without Docker)

You don't even need Docker Desktop running! RepoSage includes automatic zero-crash fallbacks.

#### 1. Start ChromaDB (Port 8000)
Double-click `backend/start-chroma.bat` or run:
```bash
cd backend
chroma run --path ./chroma_data --port 8000
```

#### 2. Configure Environment (`backend/.env`)
Make sure your Gemini API key is in `backend/.env`:
```env
PORT=5000
REDIS_URL=redis://localhost:6379
CHROMA_URL=http://localhost:8000
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
```
*(If Redis is not installed locally, RepoSage automatically switches to its built-in in-memory cache without crashing!)*

#### 3. Launch Backend & Frontend
Double-click `start-dev.bat` in the root folder, or run in separate terminals:
```bash
# Terminal 1: Backend
cd backend
npm start

# Terminal 2: Frontend
cd frontend
npm run dev
```

Open **`http://localhost:3000`** in your browser!

---

## 🎯 How to Use

1. Open the dashboard at `http://localhost:3000`.
2. Enter the path to any project (you can click **"Use Current Project"** to analyze RepoSage itself!).
3. Click **"Analyze Codebase"**:
   - Watch the live SSE progress bar scan files, parse AST functions, build the dependency graph, and synthesize Git archaeology diffs.
4. Explore the **Architecture Dependency Map** tab to inspect how modules call each other.
5. In the **AI Copilot & Archaeology** chat, ask questions like:
   - *"Explain the end-to-end data flow of this application."*
   - *"Why did we introduce Redis and ChromaDB together?"*
   - *"What modules will be impacted if we modify `astParser.js`?"*
   - *"Show me architectural decisions revealed by Git Archaeology."*
6. Review the grounded answer along with exact **file and line numbers** and **Git commit changesets**!

---

## 📁 Repository Structure

```
project-1-chrome-extension/
├── docker-compose.yml          # Multi-container orchestration (Redis, Chroma, App)
├── README.md                   # System documentation
├── start-dev.bat               # Windows one-click local launcher
├── backend/
│   ├── package.json            # Express, LangChain, ChromaDB, ioredis, simple-git
│   ├── server.js               # REST & SSE streaming server
│   ├── Dockerfile              # Containerized backend
│   ├── test-reposage.js        # Unit test suite
│   ├── start-chroma.bat        # Local ChromaDB launcher
│   ├── .env                    # Configured API keys
│   └── services/
│       ├── astParser.js        # Function/Class chunking & dependency call graph
│       ├── gitArchaeology.js   # Diff-to-intent analysis for lazy commit messages
│       ├── redisService.js     # Redis cache with in-memory fallback
│       ├── chromaService.js    # Dual collection vector storage
│       ├── ragService.js       # Multi-vector retrieval & architectural QA
│       └── llmProvider.js      # Dynamic LLM provider (Gemini / OpenAI)
└── frontend/
    ├── package.json            # React 18, Vite 6, Lucide icons
    ├── vite.config.js          # Proxy configuration to backend
    ├── Dockerfile              # Containerized frontend with Nginx
    ├── nginx.conf              # Production reverse proxy
    └── src/
        ├── App.jsx             # Main dashboard layout and tab switcher
        ├── index.css           # Modern dark-mode developer design system
        └── components/
            ├── Header.jsx           # Service health indicators (Redis, Chroma, LLM)
            ├── RepoIngestion.jsx    # Real-time SSE progress & statistics
            ├── ArchitectureGraph.jsx# Interactive module call hierarchy map
            └── ChatCopilot.jsx      # Chat with code and Git archaeology citations
```
