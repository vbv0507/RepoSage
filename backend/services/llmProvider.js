import dotenv from 'dotenv';
dotenv.config();

let embeddingsInstance = null;
let chatModelInstance = null;

export async function getEmbeddings() {
  if (embeddingsInstance) return embeddingsInstance;

  const provider = (process.env.LLM_PROVIDER || 'gemini').toLowerCase();

  if (provider === 'gemini') {
    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) {
      throw new Error('GEMINI_API_KEY is not configured in backend/.env');
    }
    const { GoogleGenerativeAIEmbeddings } = await import('@langchain/google-genai');
    embeddingsInstance = new GoogleGenerativeAIEmbeddings({
      apiKey: apiKey,
      modelName: 'models/gemini-embedding-001'
    });
    return embeddingsInstance;
  } else if (provider === 'openai') {
    const apiKey = process.env.OPENAI_API_KEY;
    if (!apiKey) {
      throw new Error(
        'OPENAI_API_KEY is not configured in backend/.env'
      );
    }
    const { OpenAIEmbeddings } = await import('@langchain/openai');
    embeddingsInstance = new OpenAIEmbeddings({
      openAIApiKey: apiKey,
      modelName: 'text-embedding-3-small'
    });
    return embeddingsInstance;
  } else {
    throw new Error(`Unsupported LLM_PROVIDER: "${provider}". Use "gemini" or "openai".`);
  }
}

/**
 * Embed an array of texts with automatic batching and rate-limit (429) backoff/retry
 */
export async function embedTextsWithRetry(texts, onProgress = () => {}) {
  if (!texts || texts.length === 0) return [];
  const model = await getEmbeddings();
  const provider = (process.env.LLM_PROVIDER || 'gemini').toLowerCase();

  if (provider === 'gemini') {
    const embeddings = [];
    const BATCH_SIZE = 15;

    for (let i = 0; i < texts.length; i += BATCH_SIZE) {
      const slice = texts.slice(i, i + BATCH_SIZE);
      let attempts = 0;
      let success = false;

      while (!success && attempts < 6) {
        attempts++;
        try {
          const req = {
            requests: slice.map(t => ({
              content: { parts: [{ text: (t || '').slice(0, 2000) }] },
              model: 'models/gemini-embedding-001'
            }))
          };
          const res = await model.client.batchEmbedContents(req);
          if (res && res.embeddings && res.embeddings.length === slice.length) {
            const vectors = res.embeddings.map(e => e.values);
            if (vectors.every(v => Array.isArray(v) && v.length > 0)) {
              embeddings.push(...vectors);
              success = true;
              break;
            }
          }
          throw new Error('Incomplete vector embeddings received from Gemini');
        } catch (err) {
          const is429 = err.message && (err.message.includes('429') || err.message.includes('Quota exceeded'));
          if (is429 && attempts < 6) {
            const match = err.message.match(/retry in ([0-9.]+)s/i);
            const waitSec = match ? Math.max(Math.ceil(parseFloat(match[1])) + 2, 20) : 20;
            onProgress({
              step: 'embedding_progress',
              message: `Gemini API quota rate-limited (${i}/${texts.length}). Waiting ${waitSec}s before resuming...`
            });
            await new Promise(r => setTimeout(r, waitSec * 1000));
          } else {
            throw err;
          }
        }
      }

      // 400ms pause between batches to smooth request bursts
      if (i + BATCH_SIZE < texts.length) {
        await new Promise(r => setTimeout(r, 400));
      }
    }

    return embeddings;
  } else {
    return await model.embedDocuments(texts.map(t => (t || '').slice(0, 2000)));
  }
}

export async function getChatModel() {
  if (chatModelInstance) return chatModelInstance;

  const provider = (process.env.LLM_PROVIDER || 'gemini').toLowerCase();

  if (provider === 'gemini') {
    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) {
      throw new Error('GEMINI_API_KEY is not configured in backend/.env');
    }
    const { ChatGoogleGenerativeAI } = await import('@langchain/google-genai');
    chatModelInstance = new ChatGoogleGenerativeAI({
      apiKey: apiKey,
      model: process.env.GEMINI_MODEL || 'gemini-3.5-flash-lite',
      temperature: 0.2,
      maxOutputTokens: 8192,
      maxRetries: 2
    });
    return chatModelInstance;
  } else if (provider === 'openai') {
    const apiKey = process.env.OPENAI_API_KEY;
    if (!apiKey) {
      throw new Error('OPENAI_API_KEY is not configured in backend/.env');
    }
    const { ChatOpenAI } = await import('@langchain/openai');
    chatModelInstance = new ChatOpenAI({
      openAIApiKey: apiKey,
      modelName: 'gpt-4o-mini',
      temperature: 0.2
    });
    return chatModelInstance;
  } else {
    throw new Error(`Unsupported LLM_PROVIDER: "${provider}". Use "gemini" or "openai".`);
  }
}

export function checkConfigStatus() {
  const provider = (process.env.LLM_PROVIDER || 'gemini').toLowerCase();
  return {
    provider,
    configured: Boolean(provider === 'gemini' ? process.env.GEMINI_API_KEY : process.env.OPENAI_API_KEY),
    model: provider === 'gemini' ? (process.env.GEMINI_MODEL || 'gemini-flash-latest') : 'gpt-4o-mini'
  };
}
