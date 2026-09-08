import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import path from 'path';
import { cacheService } from './services/redisService.js';
import { checkChromaConnection } from './services/chromaService.js';
import { checkConfigStatus } from './services/llmProvider.js';
import { ingestCodebase, queryCodebase, resolveRepoPath } from './services/ragService.js';
import { streamFullTutorial, getCachedTutorial } from './services/tutorialGenerator.js';
import { addEmailPdfJob, getJobStatus } from './services/queueService.js';

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
 * Ingest a Codebase with real-time SSE progress streaming (Supports GitHub URLs & Local Paths)
 */
app.get('/api/ingest-stream', async (req, res) => {
  const inputPath = req.query.path;

  if (!inputPath) {
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
    const resolvedPath = await resolveRepoPath(inputPath, (data) => sendEvent(data));
    sendEvent({ step: 'start', message: `Starting analysis for: ${resolvedPath}` });

    const stats = await ingestCodebase(resolvedPath, (progress) => {
      sendEvent(progress);
    });

    sendEvent({ step: 'finished', stats, resolvedPath });
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

    const resolvedPath = await resolveRepoPath(repoPath);
    const stats = await ingestCodebase(resolvedPath);
    res.json({ success: true, stats, resolvedPath });
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

    const resolvedPath = repoPath ? await resolveRepoPath(repoPath) : undefined;
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
    const inputPath = req.query.path;
    if (!inputPath) {
      return res.status(400).json({ error: 'Query parameter "path" is required.' });
    }

    const resolvedPath = await resolveRepoPath(inputPath);
    const graph = await cacheService.get(`graph:${resolvedPath}`);
    res.json(graph || { nodes: [], links: [] });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * Stream real-time generation of the Architecture Tutorial / Engineering Book
 */
app.get('/api/tutorial-stream', async (req, res) => {
  const inputPath = req.query.path;
  const forceRefresh = req.query.refresh === 'true';
  if (!inputPath) {
    return res.status(400).send('Query parameter "path" is required.');
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');

  const sendEvent = (data) => {
    res.write(`data: ${JSON.stringify(data)}\n\n`);
  };

  try {
    const resolvedPath = await resolveRepoPath(inputPath);

    // Clear cache if forced refresh
    if (forceRefresh) {
      await cacheService.del(`tutorial:${resolvedPath}`);
    }

    await streamFullTutorial(resolvedPath, (event) => {
      sendEvent(event);
    });
    res.end();
  } catch (err) {
    sendEvent({ step: 'error', error: err.message });
    res.end();
  }
});

/**
 * Get cached Architecture Tutorial
 */
app.get('/api/tutorial', async (req, res) => {
  try {
    const inputPath = req.query.path;
    if (!inputPath) {
      return res.status(400).json({ error: 'Query parameter "path" is required.' });
    }

    const resolvedPath = await resolveRepoPath(inputPath);
    const cached = await getCachedTutorial(resolvedPath);
    if (!cached) {
      return res.status(404).json({ error: 'No tutorial generated yet for this repository.' });
    }

    res.json(cached);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * Export Tutorial as a downloadable Markdown file
 */
app.post('/api/tutorial/export', async (req, res) => {
  try {
    const { repoPath } = req.body;
    if (!repoPath) {
      return res.status(400).json({ error: 'repoPath is required' });
    }

    const resolvedPath = await resolveRepoPath(repoPath);
    const cached = await getCachedTutorial(resolvedPath);
    if (!cached || !cached.fullMarkdown) {
      return res.status(404).json({ error: 'Please generate the tutorial first before exporting.' });
    }

    const filename = `${cached.repoName || 'architecture'}_tutorial.md`;
    res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
    res.setHeader('Content-Type', 'text/markdown');
    res.send(cached.fullMarkdown);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * Flush cached tutorial for a repo (forces fresh regeneration)
 */
app.delete('/api/tutorial/cache', async (req, res) => {
  try {
    const inputPath = req.query.path;
    if (!inputPath) {
      return res.status(400).json({ error: 'Query parameter "path" is required.' });
    }
    const resolvedPath = await resolveRepoPath(inputPath);
    await cacheService.del(`tutorial:${resolvedPath}`);
    res.json({ success: true, message: `Cache cleared for ${resolvedPath}` });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * Enqueue background job to generate PDF blueprint and deliver via email
 * Dispatched via BullMQ distributed queue (with zero-crash in-memory worker fallback)
 */
app.post('/api/tutorial/email', async (req, res) => {
  try {
    const { repoPath, email } = req.body;

    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return res.status(400).json({ error: 'A valid recipient email address is required.' });
    }
    if (!repoPath) {
      return res.status(400).json({ error: 'repoPath is required.' });
    }

    const resolvedPath = await resolveRepoPath(repoPath);
    const jobInfo = await addEmailPdfJob({ repoPath: resolvedPath, email });

    res.json({
      success: true,
      jobId: jobInfo.jobId,
      queueType: jobInfo.queueType,
      message: `PDF generation and email dispatch queued in ${jobInfo.queueType}.`
    });
  } catch (err) {
    console.error('[Email Queue Error]:', err.message);
    res.status(500).json({ error: err.message });
  }
});

/**
 * Poll BullMQ or In-Memory worker status for a queued documentation job
 */
app.get('/api/tutorial/email/status/:jobId', async (req, res) => {
  try {
    const { jobId } = req.params;
    if (!jobId) {
      return res.status(400).json({ error: 'Job ID parameter is required.' });
    }

    const status = await getJobStatus(jobId);
    res.json(status);
  } catch (err) {
    console.error('[Job Status Error]:', err.message);
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
