# RepoSage

> A developer tool for codebase architecture analysis, dependency mapping, and git-history intelligence using semantic retrieval.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Node.js](https://img.shields.io/badge/Node.js-%3E%3D18.0.0-339933?style=flat-square&logo=node.js&logoColor=white)](https://nodejs.org/)
[![React](https://img.shields.io/badge/React-18.3-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector%20Store-FF6F00?style=flat-square)](https://www.trychroma.com/)
[![Redis](https://img.shields.io/badge/Redis-Cache%20%26%20Queues-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io/)
[![Docker](https://img.shields.io/badge/Docker-Compose%20Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)

---

## Overview

When onboarding onto an unfamiliar or legacy codebase, developers spend hours tracing file imports, figuring out why certain architectural decisions were made, and navigating unhelpful git commit messages (`"fix"`, `"wip"`, `"update"`).

Standard text-based RAG often fails on source code because naive character/line slicing splits functions mid-scope and treats code as unstructured prose.

**RepoSage** is an open-source technical assistant that addresses this:
1. **Code-Aware Chunking**: Parses code files into logical blocks (functions, classes, endpoints, schemas) rather than slicing arbitrary line counts.
2. **Git Archaeology**: Analyzes historical `git diff` changesets and summarizes the engineering intent behind architectural shifts.
3. **Module Dependency Graphs**: Generates an interactive import/export call graph across repository files.
4. **Targeted Technical Q&A**: Answers architectural and implementation questions with exact file citations, line numbers, and historical git commit references.
5. **Technical Documentation & Diagrams**: Generates multi-chapter architectural walkthroughs with interactive Mermaid diagrams (C4 topologies, sequence flows, ERDs) and exportable PDFs.

---

## System Architecture

```
                               ┌─────────────────────────────┐
                               │   React 18 + Vite Client    │
                               │  (Responsive Web Dashboard) │
                               └──────────────┬──────────────┘
                                              │ HTTP / SSE Stream
                                              ▼
                               ┌─────────────────────────────┐
                               │     Express.js Backend      │
                               └──────────────┬──────────────┘
                                              │
                     ┌────────────────────────┼────────────────────────┐
                     ▼                        ▼                        ▼
       ┌───────────────────────────┐ ┌───────────────────┐ ┌───────────────────────┐
       │   Code Analysis Engine    │ │   Redis Service   │ │   ChromaDB Service    │
       │  - Block & Import Parser  │ │  - Query Caching  │ │  - reposage_code      │
       │  - Git Archaeology Diffs  │ │  - Graph Cache    │ │  - reposage_diffs     │
       │  - Dependency Graph Gen   │ │  - BullMQ Queue   │ │  - ONNX / Gemini Embed│
       └───────────────────────────┘ └───────────────────┘ └───────────────────────┘
```

---

## Core Technical Pipeline

### 1. Syntactic Block Extraction
Rather than cutting code arbitrarily every 500 characters, RepoSage extracts complete function declarations, classes, and exported modules across JavaScript, TypeScript, and Python files. Each chunk retains:
- File path and line range (`startLine`, `endLine`)
- Function / Class identifier
- Enclosing scope and associated imports

### 2. Git Archaeology (Diff-to-Intent Analysis)
Commit logs in real-world repos often lack descriptive explanations. RepoSage inspects recent commit diffs directly:
- Extracts file deltas and modifications from `git log` and `git diff`.
- Synthesizes technical intent summaries (e.g., *"Replaced Redis dependency with in-memory fallback to allow zero-config offline development"*).
- Indexes both raw changes and intent summaries into a dedicated vector collection (`reposage_diffs`).

### 3. Dependency Call Graph
During ingestion, import statements (`import ... from`, `require(...)`, `from ... import`) are resolved into an adjacency list of nodes and links. This powers:
- An interactive, force-directed graph to inspect coupling and circular dependencies.
- Global architectural context passed into the RAG prompt alongside retrieved code chunks.

### 4. Resilient Vector & Cache Tier
- **Vector Database**: Runs ChromaDB with persistent storage. Embeddings use a resilient multi-tier fallback:
  1. *Local ONNX runtime* (`all-MiniLM-L6-v2` via `chromadb-default-embed`) for zero-cost offline embeddings.
  2. *Google Gemini API* (`text-embedding-004`) if native ONNX bindings are unavailable.
  3. *Deterministic dimensional hashing* as a failsafe to keep the application operational during outages.
- **Smart Ingestion Cache**: If a repository has already been indexed and no new commits have been pushed, RepoSage skips re-embedding and loads existing vector counts and graphs in `<0.5s`.
- **In-Memory Graceful Fallback**: If Redis is not running locally, the server falls back to an in-memory Map and local job queue without crashing.

---

## Tech Stack

| Component | Implementation |
| :--- | :--- |
| **Frontend** | React 18, Vite 6, Vanilla CSS Design System, Mermaid.js, Cytoscape.js |
| **Backend** | Node.js (ESM), Express.js, Server-Sent Events (SSE) |
| **Vector Store** | ChromaDB (Dual collections: `reposage_code`, `reposage_diffs`) |
| **Cache & Queue** | Redis (`ioredis`), BullMQ (with in-memory fallback) |
| **LLM Integrations** | Google Gemini (`gemini-1.5-flash`, `gemini-1.5-pro`), OpenAI (`gpt-4o`, `gpt-4o-mini`) via LangChain |
| **Git & Code Parsing**| `simple-git`, custom syntactic block & import extractors |
| **PDF Generation** | PDFKit with formatted code blocks and diagram fallbacks |
| **Infrastructure** | Docker, Docker Compose, Azure Container Apps (serverless consumption) |

---

## Quickstart

### Prerequisites
- **Node.js**: `>= 18.0.0`
- **Git**: Installed and available in PATH
- **ChromaDB**: Running locally or via Docker
- **Gemini API Key** (or OpenAI API Key)

---

### Option A: Running with Docker Compose (Recommended)

Run the full stack (ChromaDB + Redis + Backend + Frontend):

```bash
# 1. Clone the repository
git clone https://github.com/vbv0507/RepoSage.git
cd RepoSage

# 2. Configure environment variables
cp backend/.env.example backend/.env
# Edit backend/.env and add your GEMINI_API_KEY

# 3. Start containers
docker compose up --build -d
```

- **Frontend**: `http://localhost:3000`
- **Backend API**: `http://localhost:5000`
- **ChromaDB**: `http://localhost:8000`

---

### Option B: Local Development Setup

#### 1. Start ChromaDB
Using Python:
```bash
pip install chromadb
chroma run --path ./chroma_data --port 8000
```
Or with Docker:
```bash
docker run -d -p 8000:8000 -v chroma_data:/chroma/chroma chromadb/chroma
```

#### 2. Backend Setup
```bash
cd backend
npm install
cp .env.example .env
# Set GEMINI_API_KEY in .env

npm start
```
The backend will run on `http://localhost:5000`.

#### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
The frontend dev server will launch at `http://localhost:3000`.

---

## API Reference

### System Health
```http
GET /api/health
```
Returns status checks for ChromaDB, Redis cache mode, and LLM configuration.

---

### Ingest Repository (Server-Sent Events)
```http
GET /api/ingest-stream?path=https://github.com/expressjs/express&force=false
```
Streams real-time analysis progress:
- `scanning`: Discovers source files while filtering ignored paths.
- `parsing_progress`: Extracts syntactic blocks and imports.
- `graph`: Constructs dependency relationships.
- `storing_code`: Indexes code chunks into ChromaDB.
- `git_archaeology`: Analyzes recent commits and diffs.
- `cache_hit`: Returned when existing vectors are already up to date.

---

### Architecture Chat
```http
POST /api/chat
Content-Type: application/json

{
  "repoPath": "https://github.com/expressjs/express",
  "question": "How does the middleware pipeline handle next() errors?",
  "refresh": false
}
```

**Example Response:**
```json
{
  "answer": "In Express, middleware error handling is defined with a four-parameter signature (err, req, res, next)...",
  "codeCitations": [
    {
      "filePath": "lib/router/layer.js",
      "name": "handle_error",
      "startLine": 62,
      "endLine": 74
    }
  ],
  "gitCitations": [
    {
      "hash": "a1b2c3d",
      "author": "developer",
      "date": "2024-03-15",
      "summary": "Updated router error propagation to handle async rejections"
    }
  ],
  "fromCache": false
}
```

---

### Module Dependency Graph
```http
GET /api/graph?path=https://github.com/expressjs/express
```
Returns nodes (files, categories, chunk counts) and directed links (imports).

---

### Architecture Tutorial Stream
```http
GET /api/tutorial-stream?path=https://github.com/expressjs/express
```
Streams a multi-chapter technical guide with embedded Mermaid diagram definitions.

---

### Export PDF Blueprint
```http
POST /api/export/pdf
Content-Type: application/json

{
  "repoPath": "https://github.com/expressjs/express",
  "email": "developer@example.com"
}
```
Compiles chapters and diagrams into a PDF blueprint and dispatches it via email or download link.

---

## Technical Trade-offs & Engineering Decisions

1. **Regex Heuristic Chunking vs. Full AST Compilers**:
   - *Current Implementation*: Regex-based pattern matching for function/class bounds to avoid heavy C++ native bindings across cross-platform environments.
   - *Trade-off*: Faster install time and smaller Docker footprint, but lacks full syntax tree validation on deeply nested closures or complex TypeScript decorators.
2. **Dual-Collection Vector Schema**:
   - Rather than bundling raw code and git diffs into a single collection, they are segregated into `reposage_code` and `reposage_diffs`. This prevents commit messages from polluting semantic code lookups while allowing multi-vector correlation during prompt construction.
3. **Graceful Cache Degradation**:
   - Redis provides sub-millisecond query caching in production, but local contributors should not be forced to configure Redis. The in-memory fallback enables zero-config local runs.
4. **Smart Ingestion Cache**:
   - RepoSage compares git commit hashes and Chroma vector counts before running embedding batches. Re-analyzing an existing repository skips redundant embedding generation, saving compute and API tokens.

---

## Directory Structure

```
RepoSage/
├── .github/workflows/
│   └── build-and-push.yml      # CI/CD: Automated GHCR build & Azure Container Apps deployment
├── docker-compose.yml          # Multi-container local orchestration
├── backend/
│   ├── Dockerfile              # Debian-slim Node.js runtime with git
│   ├── server.js               # Express API and SSE streaming handlers
│   ├── services/
│   │   ├── astParser.js        # Syntactic block chunker & import mapper
│   │   ├── gitArchaeology.js   # Git log & diff intent extractor
│   │   ├── chromaService.js    # ChromaDB dual-collection vector interface
│   │   ├── ragService.js       # RAG prompt construction & retrieval flow
│   │   ├── redisService.js     # Redis client with in-memory fallback
│   │   ├── queueService.js     # BullMQ background workers
│   │   ├── tutorialGenerator.js# Technical tutorial synthesizer
│   │   ├── pdfService.js       # PDFKit architectural document generator
│   │   └── llmProvider.js      # Unified Gemini / OpenAI client
├── frontend/
│   ├── Dockerfile              # Multi-stage build with Nginx reverse proxy
│   ├── src/
│   │   ├── App.jsx             # Root layout with responsive navigation
│   │   ├── index.css           # Minimal dark-mode developer design system
│   │   └── components/
│   │       ├── Header.jsx           # Service health indicators
│   │       ├── RepoIngestion.jsx    # SSE ingestion monitor & repository switcher
│   │       ├── ChatCopilot.jsx      # Technical Q&A with grounded citations
│   │       ├── ArchitectureGraph.jsx# Interactive module dependency graph
│   │       └── CodeTutorial.jsx     # Markdown reader with Mermaid diagrams
```

---

## License

This project is licensed under the [MIT License](LICENSE).
