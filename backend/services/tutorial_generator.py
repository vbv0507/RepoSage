import os
import re
import logging
from typing import List, Dict, Any, Callable, Optional

from .llm_provider import get_chat_model
from .chroma_service import search_codebase
from .redis_service import cache_service

try:
    from utils.mermaid_cleaner import clean_mermaid_in_markdown
except ImportError:
    from ..utils.mermaid_cleaner import clean_mermaid_in_markdown


logger = logging.getLogger("tutorial_generator")

CHAPTERS_CONFIG = [
    {
        "id": "system_overview",
        "title": "1. System Overview & Architecture Topology",
        "subtitle": "Mental Model, Component Hierarchy, and Core Technologies",
        "query": "architecture tech stack main entrypoint server database configuration overview",
        "instruction": """Provide an exhaustive, high-level mental model of the codebase architecture.
Explain what problem this system solves, the end-to-end technology stack, and directory topology.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. System C4 Topology (graph TB): Showing client/browser interfaces, API Gateway/controllers, core backend services, local vector/storage, Redis cache, and external APIs.
  2. Component Hierarchy Map (graph LR): Illustrating how the main modules, libraries, and internal utilities interconnect.
  3. End-to-End Data Processing Journey (flowchart TD): High-level journey from raw input data through the core pipeline to persisted result."""
    },
    {
        "id": "entrypoint_lifecycle",
        "title": "2. Server Entrypoint, Lifecycle & Middleware Pipeline",
        "subtitle": "Process Initialization, Environment Config, Connection Pools & Middleware Onion",
        "query": "entrypoint index server app listen port express fastapi middleware cors bodyParser helmet morgan connect",
        "instruction": """Trace the exact bootstrap process of the application from the main entrypoint file.
Detail environment variable resolution, database connection pooling, graceful shutdown handlers (SIGINT/SIGTERM), and the full order of middleware execution.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Server Bootstrap & Startup Lifecycle (flowchart TD): Showing step-by-step process boot from environment parsing to HTTP/WebSocket listening.
  2. Middleware Execution Pipeline (sequenceDiagram with autonumber): Tracing an incoming request passing through the middleware layers before reaching route controllers.
  3. Graceful Shutdown & Signal Trap Workflow (flowchart LR): Showing how SIGTERM/SIGINT signals drain connections, flush queues, and close database handles."""
    },
    {
        "id": "execution_flow",
        "title": "3. End-to-End Execution Flow & Request Routing",
        "subtitle": "Step-by-Step Lifecycle of Core User Journeys & API Request Handlers",
        "query": "request flow route endpoint api controller service prediction process data handler",
        "instruction": """Trace the comprehensive step-by-step lifecycle of primary user requests and API transactions through the system (from client -> router -> controller -> service layer -> database/cache -> response).
Cite specific controllers, methods, and services responsible for business logic.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Detailed Request-Response Sequence (sequenceDiagram with autonumber): Tracing the numbered step-by-step messages between User, Web Controller, Service Layer, and Data Tier.
  2. Controller Decision Branching Flowchart (flowchart TD): Showing input validation, error branch, cache check, core execution, and response serialization.
  3. Async Event Hand-off & Socket Broadcasting Sequence (sequenceDiagram with autonumber): Showing how background tasks or real-time event updates are broadcast to clients."""
    },
    {
        "id": "data_models",
        "title": "4. Data Layer, Schema Architecture & ERD Relationships",
        "subtitle": "Database Entities, Schemas, Relations, Indexes, and State Transitions",
        "query": "database schema sql table model entity columns foreign key migration attributes pydantic prisma mongoose",
        "instruction": """Provide an in-depth breakdown of the data architecture, database choice, and schema definitions.
Detail primary entities/tables, schemas, field types, indexes, unique constraints, foreign keys, and relational cardinality.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Database Entity-Relationship Diagram (erDiagram): Showing primary entities, attributes, primary/foreign keys, and relational cardinalities (||--o{ etc).
  2. Entity Lifecycle State Machine (stateDiagram-v2): Tracing the lifecycle of a core business record from initial creation to processed, active, cached, and archived.
  3. Data Ingestion & Field Transformation Pipeline (flowchart LR): Tracing how raw data payloads are validated, sanitized, mapped, and typed before persistence."""
    },
    {
        "id": "async_background_jobs",
        "title": "5. Background Jobs, Queues & Scheduled Tasks",
        "subtitle": "Asynchronous Workers, BullMQ/Celery/Redis Queues, Cron Schedules, and Concurrency Control",
        "query": "cron schedule worker queue bullmq celery redis job interval background task async process",
        "instruction": """Analyze how asynchronous tasks, scheduled cron jobs, and background workers operate in this repository.
Detail the task scheduler, queue architecture (BullMQ, Celery, Redis, or in-memory), worker concurrency, batching mechanisms, and job completion/retry events.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Background Worker & Queue Coordination Architecture (graph TB): Showing producers, queue brokers, concurrency workers, and Redis locks.
  2. Asynchronous Job Processing Pipeline (flowchart TD): Tracing job triggers, queue ingress, worker pickup, concurrency locks, retries with backoff, and completion.
  3. Worker-Coordinator Task Lifecycle Sequence (sequenceDiagram with autonumber): Tracing job submission, queue coordinator, worker execution, progress reporting, and final event notification."""
    },
    {
        "id": "external_integrations",
        "title": "6. External Integrations, Third-Party APIs & Scrapers",
        "subtitle": "Third-Party Services, AI Providers, Scrapers, Webhooks & Protocol Gateways",
        "query": "fetch axios httpx api client scrape puppeteer playwright external webhook thirdparty gemini telegram",
        "instruction": """Examine all external systems and third-party services integrated with this codebase (e.g. AI providers, auth providers, notification channels like Telegram/Email, web scrapers, or cloud storage).
Explain how API authentication is managed, network timeouts, retry policies, and how external responses are transformed.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. External Services Integration Topology (graph LR): Mapping the internal backend to all connected external third-party APIs and services.
  2. Resilient Third-Party API Request & Fallback Sequence (sequenceDiagram with autonumber): Tracing external API calls, rate-limit (429) detection, retry loops, and fallback invocation.
  3. Scraper & External Ingestion Flowchart (flowchart TD): Tracing target discovery, browser automation (Playwright/Puppeteer), DOM extraction, and deduplication."""
    },
    {
        "id": "security_boundaries",
        "title": "7. Security Architecture, Auth, RBAC & Trust Boundaries",
        "subtitle": "Authentication Mechanisms, Secrets, Permission Checks, and Tenant Isolation",
        "query": "security auth authentication token jwt session password isolation permission check role clerk oauth",
        "instruction": """Analyze the security posture, authentication/authorization mechanisms, and trust boundaries of this codebase.
Explain how user identity is verified, how session/JWT tokens are parsed, role-based access control (RBAC), how API endpoints are guarded, and how sensitive secrets/tokens are isolated.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Auth & Session Verification Sequence (sequenceDiagram with autonumber): Showing credential validation, token verification, and RBAC authorization checkpoints.
  2. Security Trust Boundary Map (graph TD): Showing public internet perimeter, DMZ gateway, secure application core, and isolated database tier.
  3. Role-Based Access Control (RBAC) Decision Flow (flowchart TD): Showing how permissions and user roles are evaluated before granting endpoint access."""
    },
    {
        "id": "caching_performance",
        "title": "8. Caching Strategy, State Management & Performance",
        "subtitle": "Redis Invalidation Policies, Session Stores, Query Optimization, and Memory Management",
        "query": "cache redis ttl get set memory performance pool index optimize buffer speed latency",
        "instruction": """Examine the caching architecture, memory utilization, and latency optimization techniques used in this project.
Explain Redis/in-memory cache keys, TTL (Time-to-Live) policies, cache-aside or write-through patterns, invalidation triggers, and database query optimizations.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Cache-Aside Query & Eviction Flowchart (flowchart TD): Showing cache check -> cache hit vs cache miss -> DB read -> cache populate.
  2. Cache Invalidation & Mutation Sequence (sequenceDiagram with autonumber): Showing how record mutations invalidate or update cached keys.
  3. Memory Footprint & Key Partitioning Map (graph LR): Showing key namespaces and TTL configurations."""
    },
    {
        "id": "error_handling_resilience",
        "title": "9. Error Handling, Fault Tolerance & Circuit Breakers",
        "subtitle": "Centralized Error Middleware, Retry Backoff, Fallback Engines, and Logging",
        "query": "error catch exception fallback retry circuit timeout logger status 500 404 handler HTTPException",
        "instruction": """Detail how errors, unexpected exceptions, and operational failures are intercepted and handled across the system.
Explain centralized error-handling middleware, custom application error classes, retry loops with backoff, graceful fallbacks, and observability/logging.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Fault Tolerance & Fallback Flowchart (flowchart TD): Showing error interception, retry evaluation, fallback invocation, and client response.
  2. Circuit Breaker State Transition Machine (stateDiagram-v2): Showing Closed, Open, and Half-Open states with failure counters and probe requests.
  3. Centralized Error Propagation Sequence (sequenceDiagram with autonumber): Tracing how a service-level failure propagates cleanly through the controller to the client without leaking sensitive stack traces."""
    },
    {
        "id": "developer_guide",
        "title": "10. Developer Playbook, Testing Suite & Feature Extension Guide",
        "subtitle": "Local Setup, Testing Commands, CI/CD, and Step-by-Step Feature Implementation Recipe",
        "query": "test pytest testing jest run setup command add endpoint feature extension development docker uvicorn",
        "instruction": """Provide an actionable, step-by-step playbook for developers onboarding or extending this codebase.
Detail prerequisites, environment configuration, local startup commands, and how to execute unit/integration tests.
Include a concrete tutorial on 'How to Add a New Feature or Endpoint' in this codebase with exact file creation order.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Local Dev Setup & Test Execution Pipeline (flowchart TD): Step-by-step from repository clone and dependency installation to test execution.
  2. Feature Extension Lifecycle (flowchart LR): Showing the exact order of files created, wired, and registered (Schema -> Service -> Controller -> Route -> Frontend).
  3. CI/CD Build, Test & Deployment Sequence (sequenceDiagram with autonumber): Tracing developer git push, automated lint/tests, Docker image build, and container deployment."""
    }
]

def get_repo_overview(repo_path: str) -> Dict[str, Any]:
    overview = {
        "readmeSnippet": "",
        "topLevelFiles": []
    }
    try:
        overview["topLevelFiles"] = [f for f in os.listdir(repo_path) if not f.startswith('.')]
        for fname in ["README.md", "readme.md", "README"]:
            fpath = os.path.join(repo_path, fname)
            if os.path.exists(fpath):
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    overview["readmeSnippet"] = f.read()[:2000]
                break
    except Exception:
        pass
    return overview

async def get_cached_tutorial(repo_path: str) -> Optional[Dict[str, Any]]:
    return await cache_service.get(f"tutorial:{repo_path}")

async def stream_full_tutorial(
    repo_path: str,
    on_event: Callable[[Dict[str, Any]], None]
) -> Dict[str, Any]:
    cached = await get_cached_tutorial(repo_path)
    if cached and cached.get("chapters") and len(cached["chapters"]) == len(CHAPTERS_CONFIG):
        on_event({"step": "cached", "message": "Serving cached 10-chapter architectural blueprint...", "tutorial": cached})
        return cached

    repo_name = os.path.basename(repo_path)
    overview = get_repo_overview(repo_path)
    total_chapters = len(CHAPTERS_CONFIG)

    on_event({
        "step": "start",
        "message": f"Starting 10-chapter publication-grade architectural blueprint for {repo_name}...",
        "totalChapters": total_chapters,
        "repoName": repo_name
    })

    chapters = []
    chat_model = get_chat_model(temperature=0.2)

    for i, cfg in enumerate(CHAPTERS_CONFIG):
        ch_idx = i + 1
        on_event({
            "step": "chapter_start",
            "chapterIndex": ch_idx,
            "totalChapters": total_chapters,
            "chapterId": cfg["id"],
            "title": cfg["title"],
            "subtitle": cfg["subtitle"],
            "message": f"Drafting Chapter {ch_idx}/{total_chapters}: {cfg['title']}..."
        })

        # Dual-retrieval
        search_res = await search_codebase(repo_path=repo_path, question=cfg["query"], top_k=6)
        code_snippets = []
        for c in search_res.get("codeMatches", []):
            meta = c.get("metadata", {})
            fp = meta.get("filePath", "")
            s = meta.get("startLine", 1)
            e = meta.get("endLine", 1)
            code_snippets.append(f"File: {fp} (L{s}-L{e}):\n```{meta.get('type', 'code')}\n{c.get('content')}\n```")
        
        diff_snippets = []
        for d in search_res.get("diffMatches", []):
            diff_snippets.append(f"Historical Change: {d.get('content')}")

        code_context = "\n\n".join(code_snippets)
        diff_context = "\n\n".join(diff_snippets)

        prompt = (
            f"You are the Lead Architect drafting Chapter {ch_idx} of a 10-Chapter Technical Blueprint for: {repo_name}\n\n"
            f"CHAPTER: {cfg['title']}\n"
            f"THEME: {cfg['subtitle']}\n\n"
            f"Repository Overview:\nTop Files: {', '.join(overview['topLevelFiles'][:15])}\n\n"
            f"Retrieved Code Implementations:\n{code_context}\n\n"
            + (f"Historical Git Changes:\n{diff_context}\n\n" if diff_context else "")
            + f"SPECIFIC INSTRUCTIONS FOR THIS CHAPTER:\n{cfg['instruction']}\n\n"
            "MANDATORY FORMATTING RULES:\n"
            "1. Write clear, detailed, publication-grade Markdown text with headings (###), bullet points, and code blocks.\n"
            "2. Include EXACTLY the THREE (3) specified Mermaid diagrams. Wrap every diagram strictly in ```mermaid ... ``` blocks.\n"
            "3. Clean, compile-safe Mermaid syntax: No unquoted special chars inside node labels, quote all node labels containing (), [], or :\n"
            "4. Reference specific file names and line ranges from the code context.\n\n"
            "Chapter Content:"
        )

        response = await chat_model.ainvoke(prompt)
        if isinstance(response.content, str):
            raw_content = response.content
        elif isinstance(response.content, list):
            raw_content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in response.content)
        else:
            raw_content = str(response.content)
        cleaned_content = clean_mermaid_in_markdown(raw_content)


        chapter_obj = {
            "id": cfg["id"],
            "chapterIndex": ch_idx,
            "title": cfg["title"],
            "subtitle": cfg["subtitle"],
            "content": cleaned_content
        }
        chapters.append(chapter_obj)

        on_event({
            "step": "chapter_done",
            "chapterIndex": ch_idx,
            "totalChapters": total_chapters,
            "chapter": chapter_obj,
            "message": f"Completed Chapter {ch_idx}/{total_chapters}: {cfg['title']}"
        })

    # Assemble full markdown book
    full_md_parts = [
        f"# {repo_name} - Architectural Blueprint & Engineering Book",
        f"Generated by RepoSage Principal Architect AI | {len(chapters)} Chapters\n",
        "---\n"
    ]
    for ch in chapters:
        full_md_parts.append(f"## {ch['title']}\n*{ch['subtitle']}*\n\n{ch['content']}\n\n---\n")

    full_tutorial = {
        "repoName": repo_name,
        "repoPath": repo_path,
        "totalChapters": len(chapters),
        "chapters": chapters,
        "fullMarkdown": "\n".join(full_md_parts)
    }

    await cache_service.set(f"tutorial:{repo_path}", full_tutorial, 86400 * 7)

    on_event({
        "step": "finished",
        "message": "Complete 10-chapter architectural blueprint generated and cached successfully!",
        "tutorial": full_tutorial
    })

    return full_tutorial
