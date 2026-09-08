import { Queue, Worker } from 'bullmq';
import Redis from 'ioredis';
import crypto from 'crypto';
import { generateTutorialPdf } from './pdfService.js';
import { sendTutorialEmail } from './mailService.js';
import { getCachedTutorial, streamFullTutorial } from './tutorialGenerator.js';
import dotenv from 'dotenv';
dotenv.config();

const QUEUE_NAME = 'pdf-email-queue';
const REDIS_HOST = process.env.REDIS_HOST || '127.0.0.1';
const REDIS_PORT = Number(process.env.REDIS_PORT || 6379);

// State tracking
let isRedisAvailable = false;
let bullQueue = null;
let bullWorker = null;

// In-Memory fallback store for environments without active Redis
const memoryJobs = new Map();

/**
 * Shared Core Job Execution Logic
 * Runs whether executing via BullMQ Worker or In-Memory Worker
 */
async function processEmailPdfJob({ repoPath, email }, updateProgress) {
  if (!email || !repoPath) {
    throw new Error('Both email and repoPath are required to process PDF documentation.');
  }

  updateProgress(10, 'Retrieving codebase architectural blueprint...');

  // 1. Fetch cached blueprint or generate if not created yet
  let tutorial = await getCachedTutorial(repoPath);
  if (!tutorial || !tutorial.chapters || tutorial.chapters.length === 0) {
    updateProgress(20, 'Generating complete architecture documentation via AST + RAG...');
    tutorial = await streamFullTutorial(repoPath, (evt) => {
      if (evt.step === 'chapter_start') {
        const pct = 20 + Math.floor(((evt.chapterIndex - 1) / (evt.totalChapters || 5)) * 35);
        updateProgress(pct, `Drafting Chapter ${evt.chapterIndex}/${evt.totalChapters || 5}: ${evt.title}...`);
      } else if (evt.step === 'chapter_done') {
        const pct = 20 + Math.floor((evt.chapterIndex / (evt.totalChapters || 5)) * 35);
        updateProgress(pct, `Completed Chapter ${evt.chapterIndex}/${evt.totalChapters || 5}.`);
      }
    });
  }

  // 2. Render all Mermaid diagrams to PNG images, then compile PDF
  updateProgress(55, 'Rendering architectural diagrams to images...');
  await new Promise(r => setTimeout(r, 100)); // allow progress to flush
  updateProgress(65, 'Compiling PDF blueprint with rendered diagram images...');
  const pdfBuffer = await generateTutorialPdf(tutorial);

  // 3. Dispatch email with PDF attachment
  updateProgress(85, `Sending documentation PDF to ${email}...`);
  const mailResult = await sendTutorialEmail({
    toEmail: email,
    repoName: tutorial.repoName,
    pdfBuffer
  });

  updateProgress(100, 'Documentation email delivered successfully!');

  return {
    email,
    repoName: tutorial.repoName,
    messageId: mailResult.messageId,
    previewUrl: mailResult.previewUrl,
    isEthereal: mailResult.isEthereal,
    deliveredAt: new Date().toISOString()
  };
}

/**
 * Initialize BullMQ Queue and Worker with Redis, with automatic fallback
 */
async function initQueue() {
  const probeClient = new Redis({
    host: REDIS_HOST,
    port: REDIS_PORT,
    maxRetriesPerRequest: 1,
    retryStrategy: () => null,
    connectTimeout: 800,
    lazyConnect: true
  });

  probeClient.on('error', () => {});

  try {
    await probeClient.connect();
    await probeClient.quit();
    isRedisAvailable = true;

    const connection = {
      host: REDIS_HOST,
      port: REDIS_PORT,
      maxRetriesPerRequest: null
    };

    bullQueue = new Queue(QUEUE_NAME, { connection });

    bullWorker = new Worker(
      QUEUE_NAME,
      async (job) => {
        return await processEmailPdfJob(job.data, (progress, message) => {
          job.updateProgress({ progress, message });
        });
      },
      { connection, concurrency: 3 }
    );

    bullWorker.on('completed', (job) => {
      console.log(`[BullMQ Worker] 🟢 Job ${job.id} completed successfully`);
    });

    bullWorker.on('failed', (job, err) => {
      console.error(`[BullMQ Worker] 🔴 Job ${job?.id} failed:`, err.message);
    });

    console.log(`[BullMQ] 🟢 Connected to Redis at ${REDIS_HOST}:${REDIS_PORT}. BullMQ queue initialized.`);
  } catch (err) {
    isRedisAvailable = false;
    console.log(`[Queue] ℹ️ Redis server not reachable. Utilizing high-performance in-memory job queue.`);
  }
}

// Start queue initialization
initQueue().catch((e) => {
  console.warn('[Queue] Initialization warning:', e.message);
});

/**
 * Add a new Email PDF generation job to the queue
 * @param {Object} payload - { repoPath, email }
 * @returns {Promise<{ jobId: string, queueType: string }>}
 */
export async function addEmailPdfJob({ repoPath, email }) {
  if (isRedisAvailable && bullQueue) {
    try {
      const job = await bullQueue.add(
        'email-tutorial-pdf',
        { repoPath, email },
        {
          attempts: 2,
          backoff: { type: 'exponential', delay: 2000 },
          removeOnComplete: false,
          removeOnFail: false
        }
      );
      return {
        jobId: String(job.id),
        queueType: 'BullMQ (Redis)'
      };
    } catch (e) {
      console.warn('[BullMQ] Failed to push to Redis queue, falling back to in-memory:', e.message);
    }
  }

  // Fallback: In-Memory asynchronous job runner
  const jobId = `mem_${Date.now()}_${Math.random().toString(36).substr(2, 6)}`;
  const jobState = {
    id: jobId,
    state: 'waiting',
    progress: 0,
    message: 'Job queued in background worker...',
    data: { repoPath, email },
    result: null,
    error: null,
    createdAt: new Date().toISOString()
  };

  memoryJobs.set(jobId, jobState);

  // Execute asynchronously
  setImmediate(async () => {
    jobState.state = 'active';
    try {
      const result = await processEmailPdfJob(
        { repoPath, email },
        (progress, message) => {
          jobState.progress = progress;
          jobState.message = message;
        }
      );
      jobState.state = 'completed';
      jobState.progress = 100;
      jobState.result = result;
      jobState.message = 'Email delivered successfully!';
    } catch (err) {
      jobState.state = 'failed';
      jobState.error = err.message;
      jobState.message = `Processing failed: ${err.message}`;
    }
  });

  return {
    jobId,
    queueType: 'Worker Queue (In-Memory Fallback)'
  };
}

/**
 * Retrieve status and progress of a background job
 * @param {string} jobId
 * @returns {Promise<Object>}
 */
export async function getJobStatus(jobId) {
  // 1. Check BullMQ if active and ID matches BullMQ numeric style
  if (isRedisAvailable && bullQueue && !jobId.startsWith('mem_')) {
    try {
      const job = await bullQueue.getJob(jobId);
      if (job) {
        const state = await job.getState();
        const progressData = job.progress || {};
        return {
          id: String(job.id),
          state, // 'waiting' | 'active' | 'completed' | 'failed'
          progress: typeof progressData === 'number' ? progressData : (progressData.progress || 0),
          message: typeof progressData === 'object' ? (progressData.message || '') : '',
          result: job.returnvalue || null,
          error: job.failedReason || null,
          queueType: 'BullMQ (Redis)'
        };
      }
    } catch (e) {
      // Ignore and fallback to memoryJobs check
    }
  }

  // 2. Check In-Memory Map
  const memJob = memoryJobs.get(jobId);
  if (memJob) {
    return {
      id: memJob.id,
      state: memJob.state,
      progress: memJob.progress,
      message: memJob.message,
      result: memJob.result,
      error: memJob.error,
      queueType: 'Worker Queue (In-Memory Fallback)'
    };
  }

  return {
    id: jobId,
    state: 'not_found',
    error: 'Job ID not found in queue registry'
  };
}
