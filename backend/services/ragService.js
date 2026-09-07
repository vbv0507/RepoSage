import { getEmbeddings, getChatModel } from './llmProvider.js';
import { scanDirectory, parseCodeFile, buildDependencyGraph } from './astParser.js';
import { analyzeGitArchaeology } from './gitArchaeology.js';
import * as chromaService from './chromaService.js';
import { cacheService } from './redisService.js';

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

  // Generate embeddings for code chunks
  onProgress({ step: 'embedding_code', message: `Generating vector embeddings for ${allCodeChunks.length} code blocks...` });
  const embeddingsModel = await getEmbeddings();

  const codeTexts = allCodeChunks.map(c => `${c.summary}\n${c.code}`);
  // Embed in batches
  const codeEmbeddings = [];
  const batchSize = 25;
  for (let i = 0; i < codeTexts.length; i += batchSize) {
    const batch = codeTexts.slice(i, i + batchSize);
    const batchEmbeddings = await embeddingsModel.embedDocuments(batch);
    codeEmbeddings.push(...batchEmbeddings);
  }

  // Store in ChromaDB
  onProgress({ step: 'storing_code', message: 'Saving code vectors into ChromaDB...' });
  await chromaService.storeCodeChunks({
    repoPath,
    chunks: allCodeChunks,
    embeddings: codeEmbeddings
  });

  // Analyze Git Archaeology (Diffs to Intent)
  onProgress({ step: 'git_archaeology', message: 'Performing Git Archaeology on recent commits...' });
  const diffs = await analyzeGitArchaeology(repoPath, 15);

  if (diffs.length > 0) {
    onProgress({ step: 'embedding_git', message: `Synthesizing and embedding ${diffs.length} historical Git diffs...` });
    const diffTexts = diffs.map(d => `${d.intentSummary}\n${d.diffSnippet}`);
    const diffEmbeddings = await embeddingsModel.embedDocuments(diffTexts);

    await chromaService.storeDiffSummaries({
      repoPath,
      diffs,
      embeddings: diffEmbeddings
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

  // 1. Embed user question
  const embeddingsModel = await getEmbeddings();
  const queryEmbedding = await embeddingsModel.embedQuery(question);

  // 2. Multi-vector search: Retrieve matching code and git diffs
  const { codeMatches, diffMatches } = await chromaService.searchCodebase({
    repoPath,
    queryEmbedding,
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
