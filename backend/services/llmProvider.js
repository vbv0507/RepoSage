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
      model: 'gemini-2.5-flash',
      temperature: 0.2,
      maxOutputTokens: 8192
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
    model: provider === 'gemini' ? 'gemini-2.5-flash' : 'gpt-4o-mini'
  };
}
