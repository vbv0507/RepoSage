import fs from 'fs';
import path from 'path';
import { getChatModel } from './llmProvider.js';
import { searchCodebase } from './chromaService.js';
import { cacheService } from './redisService.js';
import { cleanMermaidInMarkdown } from '../utils/mermaidCleaner.js';

export const CHAPTERS_CONFIG = [
  {
    id: 'system_overview',
    title: '1. System Overview & Architecture Topology',
    subtitle: 'Mental Model, Component Hierarchy, and Core Technologies',
    query: 'architecture tech stack main entrypoint server database configuration overview',
    instruction: `Provide an exhaustive, high-level mental model of the codebase architecture.
Explain what problem this system solves, the end-to-end technology stack, and directory topology.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. System C4 Topology (graph TB): Showing client/browser interfaces, API Gateway/controllers, core backend services, local vector/storage, Redis cache, and external APIs.
  2. Component Hierarchy Map (graph LR): Illustrating how the main modules, libraries, and internal utilities interconnect.
  3. End-to-End Data Processing Journey (flowchart TD): High-level journey from raw input data through the core pipeline to persisted result.`
  },
  {
    id: 'entrypoint_lifecycle',
    title: '2. Server Entrypoint, Lifecycle & Middleware Pipeline',
    subtitle: 'Process Initialization, Environment Config, Connection Pools & Middleware Onion',
    query: 'entrypoint index server app listen port express middleware cors bodyParser helmet morgan connect',
    instruction: `Trace the exact bootstrap process of the application from the main entrypoint file.
Detail environment variable resolution, database connection pooling, graceful shutdown handlers (SIGINT/SIGTERM), and the full order of middleware execution (CORS, security headers, request parsers, auth gates, rate limiters, error handlers).
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Server Bootstrap & Startup Lifecycle (flowchart TD): Showing step-by-step process boot from environment parsing to HTTP/WebSocket listening.
  2. Middleware Execution Pipeline (sequenceDiagram with autonumber): Tracing an incoming request passing through the middleware layers before reaching route controllers.
  3. Graceful Shutdown & Signal Trap Workflow (flowchart LR): Showing how SIGTERM/SIGINT signals drain connections, flush queues, and close database handles.`
  },
  {
    id: 'execution_flow',
    title: '3. End-to-End Execution Flow & Request Routing',
    subtitle: 'Step-by-Step Lifecycle of Core User Journeys & API Request Handlers',
    query: 'request flow route endpoint api controller service prediction process data handler',
    instruction: `Trace the comprehensive step-by-step lifecycle of primary user requests and API transactions through the system (from client -> router -> controller -> service layer -> database/cache -> response).
Cite specific controllers, methods, and services responsible for business logic.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Detailed Request-Response Sequence (sequenceDiagram with autonumber): Tracing the numbered step-by-step messages between User, Web Controller, Service Layer, and Data Tier.
  2. Controller Decision Branching Flowchart (flowchart TD): Showing input validation, error branch, cache check, core execution, and response serialization.
  3. Async Event Hand-off & Socket Broadcasting Sequence (sequenceDiagram with autonumber): Showing how background tasks or real-time event updates are broadcast to clients.`
  },
  {
    id: 'data_models',
    title: '4. Data Layer, Schema Architecture & ERD Relationships',
    subtitle: 'Database Entities, Schemas, Relations, Indexes, and State Transitions',
    query: 'database schema sql table model entity columns foreign key migration attributes mongoose',
    instruction: `Provide an in-depth breakdown of the data architecture, database choice, and schema definitions.
Detail primary entities/tables, schemas, field types, indexes, unique constraints, foreign keys, and relational cardinality.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Database Entity-Relationship Diagram (erDiagram): Showing primary entities, attributes, primary/foreign keys, and relational cardinalities (||--o{ etc).
  2. Entity Lifecycle State Machine (stateDiagram-v2): Tracing the lifecycle of a core business record from initial creation to processed, active, cached, and archived.
  3. Data Ingestion & Field Transformation Pipeline (flowchart LR): Tracing how raw data payloads are validated, sanitized, mapped, and typed before persistence.`
  },
  {
    id: 'async_background_jobs',
    title: '5. Background Jobs, Queues & Scheduled Tasks',
    subtitle: 'Asynchronous Workers, BullMQ/Redis Queues, Cron Schedules, and Concurrency Control',
    query: 'cron schedule worker queue bullmq redis job interval background task async process',
    instruction: `Analyze how asynchronous tasks, scheduled cron jobs, and background workers operate in this repository.
Detail the task scheduler, queue architecture (BullMQ, Redis, or in-memory), worker concurrency, batching mechanisms, and job completion/retry events.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Background Worker & Queue Coordination Architecture (graph TB): Showing producers, queue brokers, concurrency workers, and Redis locks.
  2. Asynchronous Job Processing Pipeline (flowchart TD): Tracing job triggers, queue ingress, worker pickup, concurrency locks, retries with backoff, and completion.
  3. Worker-Coordinator Task Lifecycle Sequence (sequenceDiagram with autonumber): Tracing job submission, queue coordinator, worker execution, progress reporting, and final event notification.`
  },
  {
    id: 'external_integrations',
    title: '6. External Integrations, Third-Party APIs & Scrapers',
    subtitle: 'Third-Party Services, AI Providers, Scrapers, Webhooks & Protocol Gateways',
    query: 'fetch axios api client scrape puppeteer playwright external webhook thirdparty gemini telegram',
    instruction: `Examine all external systems and third-party services integrated with this codebase (e.g. AI providers, auth providers, notification channels like Telegram/Email, web scrapers, ATS platforms, or cloud storage).
Explain how API authentication is managed, network timeouts, retry policies, and how external responses are transformed.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. External Services Integration Topology (graph LR): Mapping the internal backend to all connected external third-party APIs and services.
  2. Resilient Third-Party API Request & Fallback Sequence (sequenceDiagram with autonumber): Tracing external API calls, rate-limit (429) detection, retry loops, and fallback invocation.
  3. Scraper & External Ingestion Flowchart (flowchart TD): Tracing target discovery, browser automation (Playwright/Puppeteer), DOM extraction, and deduplication.`
  },
  {
    id: 'security_boundaries',
    title: '7. Security Architecture, Auth, RBAC & Trust Boundaries',
    subtitle: 'Authentication Mechanisms, Secrets, Permission Checks, and Tenant Isolation',
    query: 'security auth authentication token jwt session password isolation permission check role clerk',
    instruction: `Analyze the security posture, authentication/authorization mechanisms, and trust boundaries of this codebase.
Explain how user identity is verified, how session/JWT tokens are parsed, role-based access control (RBAC), how API endpoints are guarded, and how sensitive secrets/tokens are isolated.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Auth & Session Verification Sequence (sequenceDiagram with autonumber): Showing credential validation, token verification, and RBAC authorization checkpoints.
  2. Security Trust Boundary Map (graph TD): Showing public internet perimeter, DMZ gateway, secure application core, and isolated database tier.
  3. Role-Based Access Control (RBAC) Decision Flow (flowchart TD): Showing how permissions and user roles are evaluated before granting endpoint access.`
  },
  {
    id: 'caching_performance',
    title: '8. Caching Strategy, State Management & Performance',
    subtitle: 'Redis Invalidation Policies, Session Stores, Query Optimization, and Memory Management',
    query: 'cache redis ttl get set memory performance pool index optimize buffer speed',
    instruction: `Examine the caching architecture, memory utilization, and latency optimization techniques used in this project.
Explain Redis/in-memory cache keys, TTL (Time-to-Live) policies, cache-aside or write-through patterns, invalidation triggers, and database query optimizations (indexing, projections).
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Cache-Aside Query & Eviction Flowchart (flowchart TD): Showing cache check -> cache hit vs cache miss -> DB read -> cache populate.
  2. Cache Invalidation & Mutation Sequence (sequenceDiagram with autonumber): Showing how record mutations invalidate or update cached keys.
  3. Memory Footprint & Key Partitioning Map (graph LR): Showing key namespaces (sessions, rate limits, job payloads, scrape cache) and TTL configurations.`
  },
  {
    id: 'error_handling_resilience',
    title: '9. Error Handling, Fault Tolerance & Circuit Breakers',
    subtitle: 'Centralized Error Middleware, Retry Backoff, Fallback Engines, and Logging',
    query: 'error catch exception fallback retry circuit timeout logger status 500 404 handler',
    instruction: `Detail how errors, unexpected exceptions, and operational failures are intercepted and handled across the system.
Explain centralized error-handling middleware, custom application error classes, retry loops with backoff, graceful fallbacks (e.g. cloud LLM failing over to local heuristics), and observability/logging.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Fault Tolerance & Fallback Flowchart (flowchart TD): Showing error interception, retry evaluation, fallback invocation, and client response.
  2. Circuit Breaker State Transition Machine (stateDiagram-v2): Showing Closed, Open, and Half-Open states with failure counters and probe requests.
  3. Centralized Error Propagation Sequence (sequenceDiagram with autonumber): Tracing how a service-level failure propagates cleanly through the controller to the client without leaking sensitive stack traces.`
  },
  {
    id: 'developer_guide',
    title: '10. Developer Playbook, Testing Suite & Feature Extension Guide',
    subtitle: 'Local Setup, Testing Commands, CI/CD, and Step-by-Step Feature Implementation Recipe',
    query: 'test pytest testing jest run setup command add endpoint feature extension development docker',
    instruction: `Provide an actionable, step-by-step playbook for developers onboarding or extending this codebase.
Detail prerequisites, environment configuration, local startup commands, and how to execute unit/integration tests.
Include a concrete tutorial on 'How to Add a New Feature or Endpoint' in this codebase with exact file creation order.
You MUST include THREE (3) distinct Mermaid diagrams:
  1. Local Dev Setup & Test Execution Pipeline (flowchart TD): Step-by-step from repository clone and dependency installation to test execution.
  2. Feature Extension Lifecycle (flowchart LR): Showing the exact order of files created, wired, and registered (Schema -> Service -> Controller -> Route -> Frontend).
  3. CI/CD Build, Test & Deployment Sequence (sequenceDiagram with autonumber): Tracing developer git push, automated lint/tests, Docker image build, and container deployment.`
  }
];

/**
 * Extract manifest and top-level repository context
 */
function getRepoOverview(repoPath) {
  const overview = {
    readmeSnippet: '',
    manifestSnippet: '',
    topLevelFiles: []
  };

  try {
    const entries = fs.readdirSync(repoPath, { withFileTypes: true });
    overview.topLevelFiles = entries.map(e => (e.isDirectory() ? `${e.name}/` : e.name));

    // Read README.md if present
    const readmeFile = entries.find(e => e.name.toLowerCase() === 'readme.md');
    if (readmeFile) {
      const readmePath = path.join(repoPath, readmeFile.name);
      overview.readmeSnippet = fs.readFileSync(readmePath, 'utf-8').slice(0, 3000);
    }

    // Read package manifest if present
    const manifestFile = entries.find(e =>
      ['package.json', 'requirements.txt', 'pyproject.toml', 'cargo.toml', 'go.mod'].includes(e.name.toLowerCase())
    );
    if (manifestFile) {
      const manifestPath = path.join(repoPath, manifestFile.name);
      overview.manifestSnippet = fs.readFileSync(manifestPath, 'utf-8').slice(0, 2000);
    }
  } catch (e) {
    console.warn('[Tutorial Generator] Could not read repo root:', e.message);
  }

  return overview;
}

/**
 * Clean and validate Mermaid code block
 */
function extractAndCleanMermaid(content, expectedType) {
  const match = content.match(/```mermaid\s*([\s\S]*?)```/i);
  if (!match) return null;

  let code = match[1].trim();
  // Basic cleanup to avoid common Mermaid syntax crashes
  code = code.replace(/\\/g, '/');
  return code;
}

/**
 * Generate a single chapter with targeted code retrieval & Gemini 2.5 Flash
 */
export async function generateChapter({ repoPath, chapterConfig, repoOverview }) {
  const chatModel = await getChatModel();

  // 1. Retrieve targeted code implementations and git archaeology diffs from ChromaDB
  const { codeMatches, diffMatches } = await searchCodebase({
    repoPath,
    question: chapterConfig.query,
    topK: 6
  });

  const codeContext = codeMatches.map((c, idx) => {
    return `[Code Block ${idx + 1}] File: ${c.metadata.filePath} (Lines ${c.metadata.startLine}-${c.metadata.endLine}):\n\`\`\`\n${c.content}\n\`\`\``;
  }).join('\n\n');

  const diffContext = diffMatches.map((d, idx) => {
    return `[Historical Git Decision ${idx + 1}] Commit: ${d.metadata.hash} by ${d.metadata.author}:\n${d.content}`;
  }).join('\n\n');

  const prompt = `You are a Principal Software Architect writing a definitive, publication-quality Engineering Architecture Textbook for this repository.

Write Chapter: "${chapterConfig.title}" (${chapterConfig.subtitle}).

### Repository Context:
Top-level files: ${repoOverview.topLevelFiles.join(', ')}

${repoOverview.manifestSnippet ? `Project Dependencies Manifest:\n\`\`\`\n${repoOverview.manifestSnippet}\n\`\`\`\n` : ''}
${repoOverview.readmeSnippet ? `README Summary:\n${repoOverview.readmeSnippet.slice(0, 1000)}\n` : ''}

### Relevant Retrieved Code Implementations:
${codeContext || 'No specific code blocks retrieved.'}

${diffContext ? `### Historical Architectural Decisions:\n${diffContext}\n` : ''}

### Chapter Specific Instructions:
${chapterConfig.instruction}

### Formatting Guidelines:
1. Write in clear, authoritative engineering style with Markdown headings (##, ###).
3. You MUST include AT LEAST THREE (3) to FOUR (4) distinct, comprehensive, and valid Mermaid diagram code blocks in standard markdown (\`\`\`mermaid ... \`\`\`) to visually explain different facets of the topic:
   - Use diverse diagram types across the chapter:
     * System & Component Topology: \`graph TB\` or \`graph LR\`
     * Detailed Request & Data Sequences: \`sequenceDiagram\` with \`autonumber\`
     * Decision & Pipeline Logic: \`flowchart TD\` or \`flowchart LR\`
     * Database Schemas: \`erDiagram\`
     * Lifecycles & State Transitions: \`stateDiagram-v2\`
   - Syntax Rules for Mermaid:
     * For flowchart / graph: wrap ALL node labels in double quotes: NodeId["Clean Label (with details)"].
     * Subgraphs MUST use a single-word identifier without spaces: subgraph Subgraph_Id ["Title"].
     * For sequence diagrams: always include 'autonumber' and clean participant aliases (e.g. participant User as "Web User").
     * For ER diagrams: specify primary attributes and entity relations without spaces in attribute names.
     * For state diagrams: use [*] for start/end states and clean transition descriptions.
     * Never end lines with a semicolon (;).
     * Do NOT use HTML tags or raw backslashes (\\) inside Mermaid code. Always use forward slashes (/) for file paths.
4. Provide thorough architectural explanations before and after each diagram explaining the data flow, component topologies, and interactions.
5. Do NOT output placeholder text. Provide deep, grounded engineering explanations.

Begin writing Chapter:`;

  const response = await chatModel.invoke(prompt);
  const rawContent = typeof response.content === 'string' ? response.content : response.content?.[0]?.text || '';
  const content = cleanMermaidInMarkdown(rawContent);

  return {
    id: chapterConfig.id,
    title: chapterConfig.title,
    subtitle: chapterConfig.subtitle,
    content: content
  };
}

/**
 * Stream full tutorial generation chapter by chapter
 */
export async function streamFullTutorial(repoPath, onEvent = () => {}) {
  const cacheKey = `tutorial:${repoPath}`;
  const cached = await cacheService.get(cacheKey);

  if (cached && cached.chapters && cached.chapters.length === CHAPTERS_CONFIG.length) {
    onEvent({ step: 'cached', tutorial: cached });
    return cached;
  }

  const repoOverview = getRepoOverview(repoPath);
  const chapters = [];

  onEvent({
    step: 'start',
    message: 'Analyzing repository structure and preparing architecture curriculum...',
    totalChapters: CHAPTERS_CONFIG.length
  });

  for (let i = 0; i < CHAPTERS_CONFIG.length; i++) {
    const config = CHAPTERS_CONFIG[i];

    onEvent({
      step: 'chapter_start',
      chapterIndex: i + 1,
      totalChapters: CHAPTERS_CONFIG.length,
      chapterId: config.id,
      title: config.title,
      message: `Generating ${config.title}...`
    });

    try {
      const chapter = await generateChapter({
        repoPath,
        chapterConfig: config,
        repoOverview
      });

      chapters.push(chapter);

      onEvent({
        step: 'chapter_done',
        chapterIndex: i + 1,
        totalChapters: CHAPTERS_CONFIG.length,
        chapter
      });
    } catch (err) {
      console.error(`[Tutorial Generator] Error generating chapter ${config.title}:`, err.message);
      // Push graceful fallback chapter
      chapters.push({
        id: config.id,
        title: config.title,
        subtitle: config.subtitle,
        content: `### ${config.title}\n\n*Unable to generate complete chapter due to: ${err.message}.*`,
        mermaidDiagram: null
      });
    }
  }

  const fullMarkdown = buildFullMarkdown(repoPath, chapters);

  const tutorial = {
    repoPath,
    repoName: repoPath.split(/[/\\]/).pop(),
    generatedAt: new Date().toISOString(),
    chapters,
    fullMarkdown
  };

  // Cache in Redis for 24 hours
  await cacheService.set(cacheKey, tutorial, 86400);

  onEvent({
    step: 'complete',
    message: 'Architecture tutorial successfully generated!',
    tutorial
  });

  return tutorial;
}

/**
 * Assemble all chapters into a clean, standalone Markdown document for export
 */
export function buildFullMarkdown(repoPath, chapters) {
  const repoName = repoPath.split(/[/\\]/).pop() || 'Codebase';
  let md = `# Architecture Blueprint & Engineering Book: ${repoName}\n\n`;
  md += `*Generated autonomously by RepoSage Architecture Intelligence on ${new Date().toLocaleDateString()}*\n\n`;
  md += `## Table of Contents\n\n`;

  for (let i = 0; i < chapters.length; i++) {
    md += `${i + 1}. [${chapters[i].title}](#chapter-${chapters[i].id})\n`;
  }

  md += `\n---\n\n`;

  for (const ch of chapters) {
    md += `<a name="chapter-${ch.id}"></a>\n\n`;
    md += `${ch.content}\n\n`;
    md += `---\n\n`;
  }

  return md;
}

/**
 * Fetch cached tutorial
 */
export async function getCachedTutorial(repoPath) {
  const cacheKey = `tutorial:${repoPath}`;
  return await cacheService.get(cacheKey);
}
