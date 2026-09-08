import simpleGit from 'simple-git';
import { getChatModel } from './llmProvider.js';

const LAZY_COMMIT_PATTERNS = [
  /^fix$/i, /^wip$/i, /^update$/i, /^updates$/i, /^asdf$/i,
  /^test$/i, /^temp$/i, /^changes$/i, /^bugfix$/i, /^done$/i,
  /^minor$/i, /^commit$/i, /^clean$/i, /^refactor$/i, /^misc$/i
];

/**
 * Extract Git commit history and synthesize AI Intent Summaries from raw diffs
 * Batches lazy commits into a SINGLE LLM prompt to prevent rate limits!
 */
export async function analyzeGitArchaeology(repoPath, maxCommits = 15) {
  const git = simpleGit(repoPath);

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
  const lazyCommits = [];

  for (const commit of log.all) {
    let diff = '';
    try {
      diff = await git.show([commit.hash, '--stat', '-p']);
      diff = diff.slice(0, 1500);
    } catch (e) {
      diff = '';
    }

    const isLazy = isLazyMessage(commit.message);
    const shortHash = commit.hash.slice(0, 7);

    const record = {
      hash: shortHash,
      fullHash: commit.hash,
      author: commit.author_name,
      date: commit.date,
      rawMessage: commit.message,
      intentSummary: commit.message,
      isSynthesized: isLazy,
      diffSnippet: diff.slice(0, 800)
    };

    results.push(record);

    if (isLazy && diff.length > 50) {
      lazyCommits.push({
        hash: shortHash,
        rawMessage: commit.message,
        diffSnippet: diff.slice(0, 1200)
      });
    }
  }

  // Single batched LLM call for all lazy commits to conserve rate limits
  if (lazyCommits.length > 0) {
    try {
      const chatModel = await getChatModel();
      if (chatModel) {
        const intentMap = await batchSynthesizeDiffIntents(chatModel, lazyCommits);
        for (const item of results) {
          if (intentMap[item.hash]) {
            item.intentSummary = intentMap[item.hash];
          }
        }
      }
    } catch (e) {
      console.warn('[Git Archaeology] Batch intent synthesis skipped:', e.message);
    }
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
 * Single batched call to synthesize intent for all lazy commits at once
 */
async function batchSynthesizeDiffIntents(chatModel, lazyCommits) {
  const commitsPrompt = lazyCommits.map(c => 
    `Commit [${c.hash}] (Message: "${c.rawMessage}"):\nDiff snippet:\n${c.diffSnippet}`
  ).join('\n---\n');

  const prompt = `You are a Principal Software Architect performing Git archaeology.
The following commits have vague or uninformative commit messages.
For each commit, analyze its diff snippet and provide a 1-sentence summary of the actual architectural intent and what changed.

${commitsPrompt}

Respond strictly with valid JSON mapping each commit hash to its 1-sentence architectural summary, example:
{
  "${lazyCommits[0].hash}": "Architectural explanation of this change."
}`;

  try {
    const response = await chatModel.invoke(prompt);
    const text = typeof response.content === 'string' ? response.content : response.content?.[0]?.text || '';
    const cleanJson = text.replace(/```json/gi, '').replace(/```/g, '').trim();
    return JSON.parse(cleanJson);
  } catch (err) {
    return {};
  }
}
