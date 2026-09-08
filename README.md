# 🧠 RepoSage — AI Architectural & Legacy Codebase Intelligence Copilot

<div align="center">

![RepoSage Banner](https://img.shields.io/badge/RepoSage-Architecture%20Copilot-blue?style=for-the-badge&logo=codeforces&logoColor=white)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Node.js Version](https://img.shields.io/badge/Node.js-%3E%3D18.0.0-339933?style=flat-square&logo=node.js&logoColor=white)](https://nodejs.org/)
[![React](https://img.shields.io/badge/React-18.3-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-6.0-646CFF?style=flat-square&logo=vite&logoColor=white)](https://vitejs.dev/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector%20Store-FF6F00?style=flat-square&logo=databricks&logoColor=white)](https://www.trychroma.com/)
[![Redis](https://img.shields.io/badge/Redis-Cache%20%26%20BullMQ-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io/)
[![Google Gemini](https://img.shields.io/badge/Google%20Gemini-Flash%20%26%20Pro-4285F4?style=flat-square&logo=google&logoColor=white)](https://aistudio.google.com/)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991?style=flat-square&logo=openai&logoColor=white)](https://openai.com/)
[![Docker](https://img.shields.io/badge/Docker-Compose%20Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)

**An autonomous AI copilot that decodes legacy codebases, uncovers undocumented architectural decisions, maps dependency call hierarchies, and synthesizes executive engineering blueprints—even when developers committed with lazy messages like `"fix"`, `"wip"`, or `"update"`.**

[Features](#-key-features) • [Architecture](#-system-architecture) • [Quickstart](#-quickstart-guide) • [Docker Deployment](#-docker-compose-deployment) • [API Reference](#-api-endpoints) • [Tech Stack](#-technology-stack)

</div>

---

## 💡 The Problem: Why Standard RAG Fails on Real Codebases

When software engineers join a new company or take over a legacy repository, they face major hurdles:

1. **Commit Messages Are Useless**: In real repositories, commit history is littered with vague messages:
   ```text
   - "fix bug"
   - "wip"
   - "update stuff"
   - "refactor"
   - "asdfasdf"
   ```
   Standard RAG tools read these commit messages and hallucinate or provide zero context about *why* architectural decisions were made.
2. **Naive Line-Based Chunking Destroys Code Context**: Splitting code files every 500 characters or 50 lines cuts functions in half, separates signatures from docstrings, and breaks semantic coherence.
3. **No Global Architecture Vision**: LLMs answer questions based on single isolated snippets, missing cross-file imports, call graphs, database entity relationships, and circular dependencies.
4. **Zero Onboarding Artifacts**: Engineers spend weeks reading code manually because no up-to-date architecture documentation, C4 diagrams, sequence workflows, or onboarding guides exist.

---

## ✨ Key Features

### 1. 🔬 "Diff-to-Intent" Git Archaeology
- Automatically parses historical `git log` and inspects raw `git diff` changesets.
- Passes the code alterations through an LLM to synthesize **objective engineering intent** (e.g., *"Added Redis caching layer with fallback to resolve ChromaDB query latency on high-frequency routes"*).
- Indexes both raw changesets and synthesized intents into vector storage.

### 2. 🌲 AST-Driven Semantic Code Chunking
- Replaces arbitrary line slicing with **Abstract Syntax Tree (AST)** parsing.
- Extracts complete, syntactically intact code constructs:
  - Exported classes, methods, and functions
  - Route handlers, middleware definitions, and controllers
  - Database models, schemas, and relational entities
  - Module import/export dependency edges
- Preserves full function boundaries, file paths, line ranges, and metadata for exact citation.

### 3. 🗺️ Interactive Module & Dependency Call Graph
- Automatically constructs an interactive graph of the entire codebase.
- Visualizes file nodes, external libraries, and inter-file imports.
- Allows developers to explore call hierarchies, inspect incoming/outgoing links, and calculate ripple effects before modifying core modules.

### 4. 📚 Autonomous Multi-Chapter Architectural Blueprint
- Autonomously generates a comprehensive 7-chapter codebase guide:
  1. **System Overview & Architecture Topology**: High-level mental model and component layout.
  2. **Server Entrypoint, Lifecycle & Middleware Pipeline**: Process bootstrap, environment resolution, and middleware chain.
  3. **End-to-End Execution Flow & Request Routing**: Step-by-step trace of core user journeys and API controllers.
  4. **Data Layer, Schema Architecture & ERD Relationships**: Entities, foreign keys, and state machines.
  5. **Background Jobs, Queues & Scheduled Tasks**: BullMQ workers, async tasks, and concurrency.
  6. **Security, Auth, Rate Limiting & Trust Boundaries**: Authentication gates, input validation, and sanitization.
  7. **Developer Onboarding, Debugging & Extension Blueprint**: How to run locally, debug issues, and add new features.

### 5. 📊 Interactive Visual Mermaid Diagrams
- Every chapter includes **3 distinct, fully rendered Mermaid diagrams**:
  - C4 System Topology (`graph TB`)
  - Sequence Diagrams (`sequenceDiagram with autonumber`)
  - Entity-Relationship Diagrams (`erDiagram`)
  - State Machines (`stateDiagram-v2`)
  - Execution Decision Trees (`flowchart TD`)
- Interactive UI supporting **Pan, Zoom, Fullscreen Mode, SVG Download**, and raw syntax viewing.
- Built-in syntax sanitizer automatically fixes LLM syntax hallucinations before rendering.

### 6. 📄 Executive PDF Blueprint Export & Email Dispatch
- Compiles the complete architectural documentation into a multi-page PDF blueprint.
- High-resolution diagrams rendered using `@mermaid-js/mermaid-cli` are embedded directly into the PDF.
- Dispatches the generated PDF directly to the developer's email via Nodemailer (with Gmail, custom SMTP, or zero-config Ethereal test inbox support).

### 7. ⚡ Dual Vector Store & High-Speed Resilient Cache
- **ChromaDB Dual Collections**:
  - `reposage_code`: Active code functions, classes, and schema definitions.
  - `reposage_diffs`: Historical Git diffs and synthesized intent records.
- **Multi-Tier Caching & BullMQ Queue**:
  - Redis caches parsed dependency graphs and frequent RAG queries for sub-millisecond responses.
  - Heavy diagram and PDF compilation runs asynchronously via BullMQ.
  - **Zero-Crash In-Memory Fallback**: If Redis or BullMQ is not running, RepoSage gracefully degrades to an in-memory cache and local worker queue.

---

## 🏗️ System Architecture

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         RepoSage Frontend (React 18 + Vite)                      │
│                                                                                  │
│   ├── Repository Ingestion & Real-Time SSE Stream Monitor                        │
│   ├── Interactive Module Dependency Call Graph (Force-Directed Explorer)        │
│   ├── Architecture Copilot Chat (AST Code Citations + Git Archaeology Diff View) │
│   └── Interactive Architecture Tutorial & Blueprint (Mermaid Viewer + PDF)       │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │ REST / SSE (Port 5000)
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         RepoSage Backend (Node.js & Express)                     │
│                                                                                  │
│   ┌──────────────────────────────────────────────────────────────────────────┐   │
│   │                         Code Analysis Pipeline                           │   │
│   │   ├── AST Parser (Functions, Classes, Schemas, Imports)                  │   │
│   │   ├── Git Archaeology Engine (Diff-to-Intent LLM Synthesizer)            │   │
│   │   └── Dependency Call Graph Builder                                      │   │
│   └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│   ┌──────────────────────────────────────────────────────────────────────────┐   │
│   │                     LangChain Multi-Vector RAG Engine                    │   │
│   │   ├── Code Definitions Retriever                                         │   │
│   │   ├── Historical Git Changeset Retriever                                 │   │
│   │   └── Architectural Synthesis Chain (Google Gemini / OpenAI)             │   │
│   └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│   ┌──────────────────────────────────────────────────────────────────────────┐   │
│   │                   Documentation & Export Automation                      │   │
│   │   ├── 7-Chapter Architectural Tutorial Generator                         │   │
│   │   ├── Mermaid Sanitizer & Headless CLI Renderer                          │   │
│   │   ├── Executive PDF Document Compiler (PDFKit)                           │   │
│   │   └── BullMQ Background Queue & Nodemailer Email Service                 │   │
│   └──────────────────────────────────────────────────────────────────────────┘   │
└───────────────────────┬───────────────────────────────┬──────────────────────────┘
                        │ Caching & Queues              │ Vector Embeddings
                        ▼                               ▼
        ┌───────────────────────────────┐ ┌───────────────────────────────┐
        │       Redis (Port 6379)       │ │     ChromaDB (Port 8000)      │
        │   - Dependency Graphs Cache   │ │   - "reposage_code"           │
        │   - Sub-ms RAG Query Cache    │ │   - "reposage_diffs"          │
        │   - BullMQ Async PDF Queue    │ │   - AST & Diff Vector Search  │
        │   *(With In-Memory Fallback)* │ └───────────────────────────────┘
        └───────────────────────────────┘
```

---

## 🛠️ Technology Stack

| Domain | Technologies |
| :--- | :--- |
| **Frontend** | React 18, Vite 6, Tailwind/Custom CSS Tokens, Lucide Icons, Mermaid.js, SVG Pan-Zoom |
| **Backend** | Node.js (ESM), Express.js, Server-Sent Events (SSE), CORS |
| **AI / LLM Framework** | LangChain Core, `@langchain/google-genai`, `@langchain/openai` |
| **Supported Models** | Google Gemini (Gemini 1.5 Flash, Gemini 1.5 Pro), OpenAI (GPT-4o, GPT-4o-mini) |
| **Vector Database** | ChromaDB (`chromadb` client, `chromadb-default-embed`) |
| **Caching & Queues** | Redis (`ioredis`), BullMQ, with automatic Zero-Crash In-Memory fallback |
| **Code & Git Analysis** | Abstract Syntax Tree (AST) parsing, `simple-git`, unified diff parser |
| **Documentation & PDF** | PDFKit, `@mermaid-js/mermaid-cli`, Puppeteer headless diagram renderer |
| **Email Delivery** | Nodemailer (Gmail App Passwords, custom SMTP, Ethereal test inbox) |
| **DevOps & Containers**| Docker, Docker Compose, Multi-stage builds, Nginx production reverse proxy |

---

## 🚀 Quickstart Guide

### Prerequisites
- **Node.js**: `v18.0.0` or higher
- **Git**: Installed and available in your `PATH`
- **ChromaDB**: Running via Docker or Python
- **Google Gemini API Key** (or OpenAI API Key)

---

### Option 1: Docker Compose Deployment (All-in-One)

The simplest way to run the full stack (Redis + ChromaDB + Backend + Frontend) in isolated containers:

1. **Clone the repository**:
   ```bash
   git clone https://github.com/vbv0507/RepoSage.git
   cd RepoSage
   ```

2. **Configure your API Key**:
   Create a `backend/.env` file from `.env.example`:
   ```bash
   cp backend/.env.example backend/.env
   ```
   Add your Gemini or OpenAI API key:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

3. **Start all services**:
   ```bash
   docker compose up --build -d
   ```

4. **Access the application**:
   - **Frontend UI**: [http://localhost:3000](http://localhost:3000)
   - **Backend API**: [http://localhost:5000](http://localhost:5000)
   - **ChromaDB**: [http://localhost:8000](http://localhost:8000)
   - **Redis**: `localhost:6379`

---

### Option 2: Local Development (Without Docker)

RepoSage is designed with **zero-crash fallbacks**: if Redis or BullMQ is not installed, it automatically switches to an in-memory cache and local queue without crashing!

#### Step 1: Start ChromaDB Vector Store
If you have Python installed:
```bash
pip install chromadb
chroma run --path ./chroma_data --port 8000
```
*(On Windows, you can simply run `backend/start-chroma.bat`)*

Alternatively, run only ChromaDB in Docker:
```bash
docker run -d -p 8000:8000 -v chroma_data:/chroma/chroma chromadb/chroma
```

#### Step 2: Configure Environment Variables
Inside `backend/.env`:
```env
PORT=5000
CHROMA_URL=http://localhost:8000
REDIS_URL=redis://localhost:6379

# LLM Provider ("gemini" or "openai")
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_google_gemini_api_key

# Optional: Email Dispatch
EMAIL_USER=your_email@gmail.com
EMAIL_PASS=your_app_password
```

#### Step 3: Install Dependencies
```bash
# Install backend dependencies
cd backend
npm install

# Install frontend dependencies
cd ../frontend
npm install
```

#### Step 4: Run Development Servers
You can launch both services together on Windows by double-clicking `start-dev.bat`, or running in separate terminals:

```bash
# Terminal 1: Backend
cd backend
npm start

# Terminal 2: Frontend
cd frontend
npm run dev
```

Visit **`http://localhost:3000`** in your browser.

---

## 📖 How to Use RepoSage

### 1. Ingest Any Repository
- Paste the local filesystem path to any Git repository (or click **"Use Current Project"** to let RepoSage analyze itself).
- Click **"Analyze Codebase"**.
- Watch real-time Server-Sent Events (SSE) stream the ingestion pipeline:
  - Scanning files & filtering ignore lists
  - AST parsing code blocks (functions, classes, endpoints)
  - Generating and storing embeddings in ChromaDB
  - Synthesizing "Diff-to-Intent" Git archaeology records
  - Computing the module dependency call graph

### 2. Explore the Architecture Dependency Map
- Click the **"Architecture Map"** tab.
- Interact with the force-directed graph to see how modules interconnect.
- Click any node to view incoming dependents, outgoing imports, and file statistics.

### 3. Ask the AI Architecture Copilot
- Click the **"Copilot Chat"** tab to query the codebase:
  - *"Explain the end-to-end authentication and request lifecycle."*
  - *"Why did we introduce Redis alongside ChromaDB?"*
  - *"What functions or services will break if I modify `astParser.js`?"*
  - *"Show me architectural decisions revealed by Git archaeology."*
- Every response includes **grounded citations**, exact file paths, line ranges, and the underlying Git changeset.

### 4. Generate Interactive Tutorials & PDF Blueprints
- Click the **"Code Tutorial & Blueprint"** tab.
- Click **"Generate Blueprint"** to trigger the 7-chapter analysis.
- Inspect interactive Mermaid diagrams (zoom, pan, copy syntax, download SVG).
- Enter your email and click **"Send Blueprint to Email"** or **"Download PDF"** to generate an executive-ready architectural document.

---

## 📡 API Reference

### Health & Configuration
```http
GET /api/config-status
```
Returns connection status and configuration indicators for ChromaDB, Redis, and LLM providers.

---

### Codebase Ingestion (SSE Stream)
```http
POST /api/analyze
Content-Type: application/json

{
  "repoPath": "/path/to/local/git/repository"
}
```
Streams real-time progress events as Server-Sent Events (`step`, `progress`, `message`, `stats`).

---

### Architecture Copilot Chat
```http
POST /api/chat
Content-Type: application/json

{
  "question": "How does the caching fallback mechanism work?",
  "repoPath": "/path/to/repository"
}
```
**Response:**
```json
{
  "answer": "The caching system utilizes an ioredis client wrapped inside cacheService...",
  "codeSources": [
    {
      "filePath": "backend/services/redisService.js",
      "name": "cacheService",
      "type": "class",
      "startLine": 12,
      "endLine": 85
    }
  ],
  "gitDiffs": [
    {
      "commitHash": "8e033d8",
      "intent": "Implemented in-memory fallback map when Redis connection fails",
      "date": "2026-09-07"
    }
  ]
}
```

---

### Interactive Tutorial Stream
```http
GET /api/tutorial?repoPath=/path/to/repository
```
Streams the 7-chapter architectural documentation with interactive Mermaid diagrams in real-time SSE chunks.

---

### Async PDF & Email Dispatch
```http
POST /api/tutorial/export-pdf
Content-Type: application/json

{
  "repoPath": "/path/to/repository",
  "email": "engineer@company.com"
}
```
Enqueues a background job in BullMQ to render all diagrams, compile the PDF, and email the recipient. Returns `{ jobId: "..." }`.

---

### Background Job Status
```http
GET /api/queue-status/:jobId
```
Returns current job status (`waiting`, `active`, `completed`, `failed`), progress percentage (0-100%), and status message.

---

## 📁 Repository Structure

```
RepoSage/
├── docker-compose.yml          # Multi-container orchestration (Redis, Chroma, App)
├── README.md                   # Comprehensive system documentation
├── start-dev.bat               # Windows one-click local launcher
├── .gitignore                  # Git exclusions (prevents pushing env, cache & temp data)
├── backend/
│   ├── Dockerfile              # Backend container definition
│   ├── package.json            # Node.js backend dependencies & scripts
│   ├── server.js               # Express API, SSE streaming & endpoint handlers
│   ├── start-chroma.bat        # Local ChromaDB launcher helper
│   ├── .env.example            # Environment variable configuration template
│   ├── services/
│   │   ├── astParser.js        # AST code chunker & dependency graph builder
│   │   ├── gitArchaeology.js   # Diff-to-intent analysis for commit histories
│   │   ├── chromaService.js    # Dual-collection vector store interface
│   │   ├── redisService.js     # Redis cache with zero-crash in-memory fallback
│   │   ├── queueService.js     # BullMQ background job processor
│   │   ├── ragService.js       # LangChain multi-vector retrieval & QA chain
│   │   ├── tutorialGenerator.js# 7-Chapter architectural blueprint generator
│   │   ├── pdfService.js       # Vector-rendered PDF blueprint compiler
│   │   ├── mailService.js      # Nodemailer email dispatcher
│   │   └── llmProvider.js      # Unified provider for Gemini and OpenAI
│   └── utils/
│       ├── mermaidCleaner.js   # Mermaid syntax validation & sanitization
│       └── mermaidRenderer.js  # Headless CLI rendering of Mermaid to PNG
└── frontend/
    ├── Dockerfile              # Frontend multi-stage container build
    ├── nginx.conf              # Production Nginx reverse proxy configuration
    ├── package.json            # React & Vite frontend dependencies
    ├── vite.config.js          # Vite build config with backend proxy
    ├── index.html              # HTML entry point
    └── src/
        ├── main.jsx            # React root mount
        ├── App.jsx             # Main dashboard layout and navigation tabs
        ├── index.css           # Modern dark-mode developer UI design system
        ├── components/
        │   ├── Header.jsx           # Service health indicators (Chroma, Redis, LLM)
        │   ├── RepoIngestion.jsx    # Real-time SSE progress & ingestion controls
        │   ├── ArchitectureGraph.jsx# Force-directed interactive module call graph
        │   ├── ChatCopilot.jsx      # AI chat with grounded code & Git diff traces
        │   └── CodeTutorial.jsx     # Interactive Mermaid tutorial & PDF export UI
        └── utils/
            └── mermaidCleaner.js    # Client-side Mermaid syntax cleaner
```

---

## 🔒 Security & Privacy Best Practices

- **Zero Secret Commits**: All sensitive keys (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `EMAIL_PASS`) are isolated in `backend/.env` which is strictly excluded in `.gitignore`.
- **Local Analysis**: Code analyzed by RepoSage remains on your local machine or private container; only prompt chunks are sent to the designated LLM provider API.
- **Isolated Clones**: Temporary repositories cloned for analysis are kept in `backend/cloned_repos/`, which is ignored by Git and never committed.

---

## 🤝 Contributing

Contributions, feature requests, and issue reports are welcome!

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m "feat: add amazing feature"`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

<div align="center">
Made with ❤️ for developers who hate reading bad commit messages and legacy spaghetti code.
</div>
