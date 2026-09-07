import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import path from 'path';
import { cacheService } from './services/redisService.js';
import { checkChromaConnection } from './services/chromaService.js';
import { checkConfigStatus } from './services/llmProvider.js';
import { ingestCodebase, queryCodebase } from './services/ragService.js';

dotenv.config();

const app = express();
const PORT = process.env.PORT || 5000;

app.use(cors());
app.use(express.json({ limit: '50mb' }));

/**
 * System Health & Status Check
 */
app.get('/api/health', async (req, res) => {
  const chroma = await checkChromaConnection();
  const redisStatus = cacheService.getStatus();
  const llm = checkConfigStatus();

  res.json({
    status: 'ok',
    services: {
      redis: redisStatus,
      chroma: chroma,
      llm: llm
    }
  });
});

/**
 * Ingest a Codebase with real-time SSE progress streaming
 */
app.get('/api/ingest-stream', async (req, res) => {
  const repoPath = req.query.path;

  if (!repoPath) {
    return res.status(400).send('Query parameter "path" is required.');
  }

  // Set SSE headers
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');

  const sendEvent = (data) => {
    res.write(`data: ${JSON.stringify(data)}\n\n`);
  };

  try {
    const resolvedPath = path.resolve(repoPath);
    sendEvent({ step: 'start', message: `Starting ingestion for: ${resolvedPath}` });

    const stats = await ingestCodebase(resolvedPath, (progress) => {
      sendEvent(progress);
    });

    sendEvent({ step: 'finished', stats });
    res.end();
  } catch (err) {
    sendEvent({ step: 'error', error: err.message });
    res.end();
  }
});

/**
 * Simple POST Ingestion endpoint
 */
app.post('/api/ingest', async (req, res) => {
  try {
    const { repoPath } = req.body;
    if (!repoPath) {
      return res.status(400).json({ error: 'repoPath is required' });
    }

    const resolvedPath = path.resolve(repoPath);
    const stats = await ingestCodebase(resolvedPath);
    res.json({ success: true, stats });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

/**
 * Ask architectural and technical questions about the codebase
 */
app.post('/api/chat', async (req, res) => {
  try {
    const { repoPath, question, refresh } = req.body;
    if (!question) {
      return res.status(400).json({ error: 'question is required' });
    }

    const resolvedPath = repoPath ? path.resolve(repoPath) : undefined;
    const response = await queryCodebase({ repoPath: resolvedPath, question, refresh });
    res.json(response);
  } catch (err) {
    console.error('[Chat Error]:', err.message);
    res.status(500).json({ error: err.message });
  }
});

/**
 * Get the Architectural Dependency Graph for visualization
 */
app.get('/api/graph', async (req, res) => {
  try {
    const repoPath = req.query.path ? path.resolve(req.query.path) : null;
    if (!repoPath) {
      return res.status(400).json({ error: 'Query parameter "path" is required.' });
    }

    const graph = await cacheService.get(`graph:${repoPath}`);
    res.json(graph || { nodes: [], links: [] });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, () => {
  console.log('===========================================================');
  console.log(`🧠 RepoSage Backend Server active on http://localhost:${PORT}`);
  console.log(`📦 Vector DB (Chroma): ${process.env.CHROMA_URL || 'http://localhost:8000'}`);
  console.log(`⚡ Cache Layer (Redis): ${process.env.REDIS_URL || 'redis://localhost:6379'}`);
  console.log('===========================================================');
});
