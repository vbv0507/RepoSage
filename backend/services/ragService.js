import simpleGit from 'simple-git';
import fs from 'fs';
import path from 'path';
import { getEmbeddings, getChatModel, embedTextsWithRetry } from './llmProvider.js';
import { scanDirectory, parseCodeFile, buildDependencyGraph } from './astParser.js';
import { analyzeGitArchaeology } from './gitArchaeology.js';
import * as chromaService from './chromaService.js';
import { cacheService } from './redisService.js';

/**
 * Resolve local folder path or auto-clone remote GitHub repository
 */
export async function resolveRepoPath(inputPath, onProgress = () => {}) {
  if (!inputPath) throw new Error('Repository path or URL is required.');
  const trimmed = inputPath.trim();

  // Check if it's a remote Git URL
  const isRemote = /^(https?:\/\/|git@)/i.test(trimmed);
  if (!isRemote) {
    return path.resolve(trimmed);
  }

  const repoName = trimmed.split('/').pop().replace(/\.git$/i, '') || 'remote_repo';
  const cloneBase = path.resolve('./cloned_repos');
  if (!fs.existsSync(cloneBase)) fs.mkdirSync(cloneBase, { recursive: true });
  const targetDir = path.join(cloneBase, repoName);

  if (!fs.existsSync(targetDir)) {
    onProgress({ step: 'cloning', message: `Cloning remote GitHub repository: ${trimmed}...` });
    const git = simpleGit();
    try {
      await git.clone(trimmed, targetDir, ['--depth', '30']);
      onProgress({ step: 'cloned', message: `Successfully cloned ${repoName}.` });
    } catch (err) {
      throw new Error(`Failed to clone remote repository: ${err.message}`);
    }
  } else {
    onProgress({ step: 'cloning', message: `Syncing repository: pulling latest commits for ${repoName}...` });
    try {
      const git = simpleGit(targetDir);
      await git.pull();
      onProgress({ step: 'cloned', message: `Successfully updated ${repoName} to latest commit.` });
    } catch (err) {
      console.warn(`[Git] Pull failed for ${repoName}, continuing with existing clone:`, err.message);
      onProgress({ step: 'cloned', message: `Using existing clone for ${repoName}.` });
    }
  }

  return targetDir;
}

/**
 * Ingest a codebase: Scan, AST parse, build graph, analyze git diffs, embed & store
 */
export async function ingestCodebase(repoPath, onProgress = () => {}) {
  // Clear cached queries so fresh and updated answers are generated
  await cacheService.clearQueries();

  onProgress({ step: 'scanning', message: `Scanning files in ${repoPath}...` });
  const filePaths = scanDirectory(repoPath);

  if (filePaths.length === 0) {
    throw new Error(`No code files found in directory: ${repoPath}`);
  }

  onProgress({ step: 'parsing', message: `Parsing AST structures for ${filePaths.length} files...`, totalFiles: filePaths.length });

  const parsedFiles = [];
  const allCodeChunks = [];

  for (let i = 0; i < filePaths.length; i++) {
    const file = parseCodeFile(filePaths[i], repoPath);
    parsedFiles.push(file);
    allCodeChunks.push(...file.chunks);
    if ((i + 1) % 10 === 0 || i === filePaths.length - 1) {
      onProgress({ step: 'parsing_progress', current: i + 1, total: filePaths.length });
    }
  }

  // Build dependency graph and cache in Redis
  onProgress({ step: 'graph', message: 'Building architectural dependency graph...' });
  const dependencyGraph = buildDependencyGraph(parsedFiles);
  await cacheService.set(`graph:${repoPath}`, dependencyGraph, 86400);

  // Store in ChromaDB (local ONNX vector model: zero API calls, zero rate limits)
  onProgress({ step: 'storing_code', message: `Indexing and storing ${allCodeChunks.length} code blocks into vector database...` });
  await chromaService.storeCodeChunks({
    repoPath,
    chunks: allCodeChunks
  });

  // Analyze Git Archaeology (Diffs to Intent)
  onProgress({ step: 'git_archaeology', message: 'Performing Git Archaeology on recent commits...' });
  const diffs = await analyzeGitArchaeology(repoPath, 15);

  if (diffs.length > 0) {
    onProgress({ step: 'embedding_git', message: `Indexing ${diffs.length} historical Git diffs into vector database...` });
    await chromaService.storeDiffSummaries({
      repoPath,
      diffs
    });
  }

  onProgress({ step: 'complete', message: 'Repository ingestion complete!' });

  return {
    repoPath,
    filesCount: filePaths.length,
    chunksCount: allCodeChunks.length,
    gitDiffsCount: diffs.length,
    graphNodesCount: dependencyGraph.nodes.length,
    graphLinksCount: dependencyGraph.links.length
  };
}

/**
 * Ask architectural and implementation questions about the ingested codebase
 */
export async function queryCodebase({ repoPath, question, refresh = false }) {
  if (!question) throw new Error('Question is required.');

  const cacheKey = `query:${repoPath}:${question.trim().toLowerCase()}`;
  if (!refresh) {
    const cachedResponse = await cacheService.get(cacheKey);
    // Only serve from cache if it was a complete answer
    if (cachedResponse && cachedResponse.answer && cachedResponse.answer.length > 300) {
      console.log(`[Cache] ⚡ Returning cached response from Redis for: "${question}"`);
      return { ...cachedResponse, fromCache: true };
    }
  }

  // 1. Multi-vector search: Retrieve matching code and git diffs using local vector model
  const { codeMatches, diffMatches } = await chromaService.searchCodebase({
    repoPath,
    question,
    topK: 5
  });

  // 3. Fetch cached dependency graph summary from Redis
  const cachedGraph = await cacheService.get(`graph:${repoPath}`);
  let graphContext = '';
  if (cachedGraph && cachedGraph.links && cachedGraph.links.length > 0) {
    const topLinks = cachedGraph.links.slice(0, 10).map(l => `${l.source} -> ${l.target}`).join('\n');
    graphContext = `Known Architecture Connections:\n${topLinks}\n\n`;
  }

  // 4. Format context
  const codeContext = codeMatches.map((c, i) => {
    return `[Code Block ${i + 1}] File: ${c.metadata.filePath} (Lines ${c.metadata.startLine}-${c.metadata.endLine}):\n\`\`\`\n${c.content}\n\`\`\``;
  }).join('\n\n');

  const diffContext = diffMatches.map((d, i) => {
    return `[Git Archaeology ${i + 1}] Commit: ${d.metadata.hash} by ${d.metadata.author} (${d.metadata.date}):\nIntent Summary: ${d.content}`;
  }).join('\n\n');

  // 5. Build prompt
  const systemPrompt = `You are RepoSage, a Principal Software Architect AI specializing in legacy codebase intelligence and architectural decision tracing.

Your goal is to answer the developer's question accurately, citing specific files, functions, line numbers, and historical git reasons.

Repository Context:
${graphContext}
Retrieved Code Implementations:
${codeContext}

${diffContext ? `Retrieved Historical Git Changes (Why it was built this way):\n${diffContext}` : ''}

Developer Question: ${question}

Instructions:
- Explain the architectural reason and technical flow.
- Reference exact file names and line ranges when discussing code.
- If historical diffs provide context on WHY a decision or change was made, highlight it under a "🏛️ Architectural Decision History" section.
- Use clean Markdown format with code snippets where helpful.

Answer:`;

  const chatModel = await getChatModel();
  const response = await chatModel.invoke(systemPrompt);
  const answerText = typeof response.content === 'string' ? response.content : response.content?.[0]?.text || '';

  const result = {
    answer: answerText,
    codeCitations: codeMatches.map(c => ({
      filePath: c.metadata.filePath,
      name: c.metadata.name,
      startLine: c.metadata.startLine,
      endLine: c.metadata.endLine,
      snippet: c.content.slice(0, 300)
    })),
    gitCitations: diffMatches.map(d => ({
      hash: d.metadata.hash,
      author: d.metadata.author,
      date: d.metadata.date,
      summary: d.content.slice(0, 200)
    }))
  };

  // Cache in Redis for 1 hour
  await cacheService.set(cacheKey, result, 3600);

  return result;
}
