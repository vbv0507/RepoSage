import { ChromaClient } from 'chromadb';
import dotenv from 'dotenv';
dotenv.config();

const CHROMA_URL = process.env.CHROMA_URL || 'http://localhost:8000';

let client = null;
let codeCollection = null;
let diffsCollection = null;

export function getChromaClient() {
  if (!client) {
    client = new ChromaClient({ path: CHROMA_URL });
  }
  return client;
}

export async function checkChromaConnection() {
  try {
    const c = getChromaClient();
    const heartbeat = await c.heartbeat();
    return { connected: true, heartbeat };
  } catch (err) {
    return { connected: false, error: err.message };
  }
}

export async function getCodeCollection() {
  if (codeCollection) return codeCollection;
  const c = getChromaClient();
  codeCollection = await c.getOrCreateCollection({
    name: 'reposage_code',
    metadata: { 'hnsw:space': 'cosine' }
  });
  return codeCollection;
}

export async function getDiffsCollection() {
  if (diffsCollection) return diffsCollection;
  const c = getChromaClient();
  diffsCollection = await c.getOrCreateCollection({
    name: 'reposage_diffs',
    metadata: { 'hnsw:space': 'cosine' }
  });
  return diffsCollection;
}

/**
 * Store parsed code chunks into ChromaDB
 */
export async function storeCodeChunks({ repoPath, chunks, embeddings }) {
  const coll = await getCodeCollection();

  // Clear previous vectors for this repo
  try {
    await coll.delete({ where: { repoPath: repoPath } });
  } catch (e) {}

  const ids = [];
  const documents = [];
  const metadatas = [];

  for (let i = 0; i < chunks.length; i++) {
    const chunk = chunks[i];
    ids.push(`code_${Buffer.from(chunk.filePath + ':' + chunk.startLine).toString('base64').slice(0, 16)}_${i}`);
    documents.push(chunk.code);
    metadatas.push({
      repoPath: repoPath,
      filePath: chunk.filePath,
      name: chunk.name || 'unnamed',
      type: chunk.type || 'code',
      startLine: chunk.startLine || 1,
      endLine: chunk.endLine || 1,
      summary: chunk.summary || ''
    });
  }

  await coll.add({
    ids,
    embeddings,
    metadatas,
    documents
  });

  return { storedCount: chunks.length };
}

/**
 * Store Git archaeology diff summaries into ChromaDB
 */
export async function storeDiffSummaries({ repoPath, diffs, embeddings }) {
  if (!diffs || diffs.length === 0) return { storedCount: 0 };
  const coll = await getDiffsCollection();

  try {
    await coll.delete({ where: { repoPath: repoPath } });
  } catch (e) {}

  const ids = [];
  const documents = [];
  const metadatas = [];

  for (let i = 0; i < diffs.length; i++) {
    const diff = diffs[i];
    ids.push(`diff_${diff.hash}_${i}`);
    documents.push(`${diff.intentSummary}\n\nDiff details:\n${diff.diffSnippet}`);
    metadatas.push({
      repoPath: repoPath,
      hash: diff.hash,
      author: diff.author || 'Unknown',
      date: diff.date || '',
      rawMessage: diff.rawMessage || '',
      isSynthesized: diff.isSynthesized ? 'true' : 'false'
    });
  }

  await coll.add({
    ids,
    embeddings,
    metadatas,
    documents
  });

  return { storedCount: diffs.length };
}

/**
 * Multi-vector search: finds relevant code blocks and git diffs
 */
export async function searchCodebase({ repoPath, queryEmbedding, topK = 4 }) {
  const codeColl = await getCodeCollection();
  const diffsColl = await getDiffsCollection();

  const where = repoPath ? { repoPath } : undefined;

  // Query code
  const codeRes = await codeColl.query({
    queryEmbeddings: [queryEmbedding],
    nResults: topK,
    where
  });

  // Query historical diffs
  let diffsRes = null;
  try {
    diffsRes = await diffsColl.query({
      queryEmbeddings: [queryEmbedding],
      nResults: 2,
      where
    });
  } catch (e) {
    diffsRes = null;
  }

  const codeMatches = [];
  if (codeRes && codeRes.documents && codeRes.documents[0]) {
    for (let i = 0; i < codeRes.documents[0].length; i++) {
      codeMatches.push({
        type: 'code',
        content: codeRes.documents[0][i],
        metadata: codeRes.metadatas[0] ? codeRes.metadatas[0][i] : {},
        distance: codeRes.distances ? codeRes.distances[0][i] : null
      });
    }
  }

  const diffMatches = [];
  if (diffsRes && diffsRes.documents && diffsRes.documents[0]) {
    for (let i = 0; i < diffsRes.documents[0].length; i++) {
      diffMatches.push({
        type: 'git_archaeology',
        content: diffsRes.documents[0][i],
        metadata: diffsRes.metadatas[0] ? diffsRes.metadatas[0][i] : {},
        distance: diffsRes.distances ? diffsRes.distances[0][i] : null
      });
    }
  }

  return {
    codeMatches,
    diffMatches
  };
}

export async function clearRepoVectors(repoPath) {
  try {
    const codeColl = await getCodeCollection();
    const diffsColl = await getDiffsCollection();
    await codeColl.delete({ where: { repoPath } });
    await diffsColl.delete({ where: { repoPath } });
    return { success: true };
  } catch (e) {
    return { success: false, error: e.message };
  }
}
