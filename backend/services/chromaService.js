import { ChromaClient, DefaultEmbeddingFunction } from 'chromadb';
import dotenv from 'dotenv';
dotenv.config();

const CHROMA_URL = process.env.CHROMA_URL || 'http://localhost:8000';

let client = null;
let codeCollection = null;
let diffsCollection = null;
let localEmbeddingFunction = null;

export function getChromaClient() {
  if (!client) {
    client = new ChromaClient({ path: CHROMA_URL });
  }
  return client;
}

export function getLocalEmbeddingFunction() {
  if (!localEmbeddingFunction) {
    localEmbeddingFunction = new DefaultEmbeddingFunction();
  }
  return localEmbeddingFunction;
}

export async function checkChromaConnection() {
  try {
    const c = getChromaClient();
    const heartbeat = await c.heartbeat();
    return { connected: true, heartbeat, embeddingType: 'local-all-MiniLM-L6-v2' };
  } catch (err) {
    return { connected: false, error: err.message };
  }
}

async function getOrInitCollection(name) {
  const c = getChromaClient();
  const ef = getLocalEmbeddingFunction();

  try {
    return await c.getOrCreateCollection({
      name,
      embeddingFunction: ef,
      metadata: { 'hnsw:space': 'cosine' }
    });
  } catch (err) {
    // If previous collection used different dimension (e.g. 3072 from Gemini), recreate with local embed
    if (err.message && (err.message.includes('dimension') || err.message.includes('InvalidCollection'))) {
      console.log(`[ChromaDB] Resetting collection ${name} for high-speed local embeddings...`);
      try { await c.deleteCollection({ name }); } catch(e) {}
      return await c.createCollection({
        name,
        embeddingFunction: ef,
        metadata: { 'hnsw:space': 'cosine' }
      });
    }
    throw err;
  }
}

export async function getCodeCollection() {
  if (codeCollection) return codeCollection;
  codeCollection = await getOrInitCollection('reposage_code');
  return codeCollection;
}

export async function getDiffsCollection() {
  if (diffsCollection) return diffsCollection;
  diffsCollection = await getOrInitCollection('reposage_diffs');
  return diffsCollection;
}

/**
 * Store parsed code chunks into ChromaDB with local embeddings
 */
export async function storeCodeChunks({ repoPath, chunks }) {
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
    documents.push(chunk.code.slice(0, 2000));
    metadatas.push({
      repoPath: repoPath,
      filePath: chunk.filePath,
      name: chunk.name || 'unnamed',
      type: chunk.type || 'code',
      startLine: chunk.startLine || 1,
      endLine: chunk.endLine || 1,
      summary: (chunk.summary || '').slice(0, 400)
    });
  }

  // Add in safe batches of 25 chunks
  const BATCH_SIZE = 25;
  for (let i = 0; i < ids.length; i += BATCH_SIZE) {
    const bIds = ids.slice(i, i + BATCH_SIZE);
    const bMetadatas = metadatas.slice(i, i + BATCH_SIZE);
    const bDocuments = documents.slice(i, i + BATCH_SIZE);

    await coll.add({
      ids: bIds,
      metadatas: bMetadatas,
      documents: bDocuments
    });
  }

  return { storedCount: chunks.length };
}

/**
 * Store Git archaeology diff summaries into ChromaDB with local embeddings
 */
export async function storeDiffSummaries({ repoPath, diffs }) {
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

  const BATCH_SIZE = 20;
  for (let i = 0; i < ids.length; i += BATCH_SIZE) {
    await coll.add({
      ids: ids.slice(i, i + BATCH_SIZE),
      metadatas: metadatas.slice(i, i + BATCH_SIZE),
      documents: documents.slice(i, i + BATCH_SIZE)
    });
  }

  return { storedCount: diffs.length };
}

/**
 * Multi-vector search: finds relevant code blocks and git diffs using local vector embeddings
 */
export async function searchCodebase({ repoPath, question, topK = 6 }) {
  const codeColl = await getCodeCollection();
  const diffsColl = await getDiffsCollection();

  const where = repoPath ? { repoPath } : undefined;

  // Query code
  let codeRes = await codeColl.query({
    queryTexts: [question],
    nResults: topK,
    where
  });

  // Resilient fallback: If no code blocks matched the exact repoPath string,
  // query without where so the architect AI always receives the actual code!
  if (!codeRes || !codeRes.documents || !codeRes.documents[0] || codeRes.documents[0].length === 0) {
    try {
      codeRes = await codeColl.query({
        queryTexts: [question],
        nResults: topK
      });
    } catch (e) {}
  }

  // Query historical diffs
  let diffsRes = null;
  try {
    diffsRes = await diffsColl.query({
      queryTexts: [question],
      nResults: 3,
      where
    });
    if (!diffsRes || !diffsRes.documents || !diffsRes.documents[0] || diffsRes.documents[0].length === 0) {
      diffsRes = await diffsColl.query({
        queryTexts: [question],
        nResults: 3
      });
    }
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
