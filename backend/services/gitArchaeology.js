import simpleGit from 'simple-git';
import { getChatModel } from './llmProvider.js';

const LAZY_COMMIT_PATTERNS = [
  /^fix$/i, /^wip$/i, /^update$/i, /^updates$/i, /^asdf$/i,
  /^test$/i, /^temp$/i, /^changes$/i, /^bugfix$/i, /^done$/i,
  /^minor$/i, /^commit$/i, /^clean$/i, /^refactor$/i, /^misc$/i
];

/**
 * Extract Git commit history and synthesize AI Intent Summaries from raw diffs
 */
export async function analyzeGitArchaeology(repoPath, maxCommits = 15) {
  const git = simpleGit(repoPath);

  // Check if directory is a valid git repository
  let isRepo = false;
  try {
    isRepo = await git.checkIsRepo();
  } catch (e) {
    isRepo = false;
  }

  if (!isRepo) {
    console.log(`[Git Archaeology] "${repoPath}" is not a Git repository. Skipping commit history.`);
    return [];
  }

  let log = null;
  try {
    log = await git.log({ maxCount: maxCommits });
  } catch (err) {
    console.warn('[Git Archaeology] Could not read git log:', err.message);
    return [];
  }

  const results = [];
  let chatModel = null;
  try {
    chatModel = await getChatModel();
  } catch (e) {
    // LLM not configured yet
  }

  for (const commit of log.all) {
    let diff = '';
    try {
      diff = await git.show([commit.hash, '--stat', '-p']);
      // Cap diff to prevent massive prompt overflow
      diff = diff.slice(0, 3000);
    } catch (e) {
      diff = '';
    }

    const isLazy = isLazyMessage(commit.message);
    let intentSummary = commit.message;

    // If commit message is lazy/uninformative AND LLM is available, synthesize intent from diff!
    if (isLazy && chatModel && diff.length > 50) {
      try {
        intentSummary = await synthesizeDiffIntent(chatModel, commit.message, diff);
      } catch (err) {
        intentSummary = `Code change: ${commit.message}`;
      }
    }

    results.push({
      hash: commit.hash.slice(0, 7),
      fullHash: commit.hash,
      author: commit.author_name,
      date: commit.date,
      rawMessage: commit.message,
      intentSummary: intentSummary,
      isSynthesized: isLazy,
      diffSnippet: diff.slice(0, 1000)
    });
  }

  return results;
}

/**
 * Checks if a commit message is uninformative
 */
function isLazyMessage(msg) {
  const trimmed = (msg || '').trim();
  if (trimmed.length <= 8) return true;
  for (const pattern of LAZY_COMMIT_PATTERNS) {
    if (pattern.test(trimmed)) return true;
  }
  return false;
}

/**
 * Use LLM to analyze the code diff and explain what actually changed and why
 */
async function synthesizeDiffIntent(chatModel, rawMsg, diff) {
  const prompt = `You are an expert software architect performing Git code archaeology.
A developer committed code with the vague commit message: "${rawMsg}".
Analyze the following code diff and explain what architectural change was actually made and its likely intent in 1 to 2 concise sentences.

Code Diff:
${diff}

Concise Architectural Summary:`;

  const response = await chatModel.invoke(prompt);
  const text = typeof response.content === 'string' ? response.content : response.content?.[0]?.text || '';
  return text.trim() || rawMsg;
}
