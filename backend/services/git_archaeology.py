import os
import logging
from typing import List, Dict, Any
from git import Repo
from .llm_provider import get_chat_model

logger = logging.getLogger("git_archaeology")

async def analyze_git_archaeology(repo_path: str, max_commits: int = 15) -> List[Dict[str, Any]]:
    diff_summaries = []
    try:
        repo = Repo(repo_path)
        if not repo.heads:
            return []
        
        commits = list(repo.iter_commits(max_count=max_commits))
    except Exception as e:
        logger.warning(f"Git archaeology unavailable for {repo_path}: {e}")
        return []

    # A forced re-index must not wait for up to one cloud LLM request per
    # commit. Commit messages and diff snippets are already useful grounded
    # archaeology context. Opt into costly generated summaries explicitly.
    chat_model = None
    if os.getenv("GIT_ARCHAEOLOGY_LLM_SUMMARIES", "false").lower() in {"1", "true", "yes"}:
        try:
            chat_model = get_chat_model(temperature=0.1)
        except Exception:
            pass

    for commit in commits:
        try:
            h = commit.hexsha[:8]
            msg = commit.message.strip()
            author = commit.author.name or "Unknown"
            date = str(commit.committed_datetime)

            # Get diff with parent
            diff_text = ""
            if commit.parents:
                parent = commit.parents[0]
                diffs = parent.diff(commit, create_patch=True)
                patches = []
                for d in diffs[:5]:
                    if d.diff:
                        try:
                            patches.append(d.diff.decode('utf-8', errors='ignore'))
                        except Exception:
                            pass
                diff_text = "\n".join(patches)[:2000]
            else:
                diff_text = "Initial commit."

            intent = f"Commit {h}: {msg}"
            is_synthesized = False

            # Synthesize intent using LangChain
            if chat_model and diff_text:
                try:
                    prompt = (
                        f"Summarize the architectural and technical intent of this Git commit in 2-3 sentences:\n"
                        f"Commit Message: {msg}\n"
                        f"Diff Snippet:\n{diff_text[:1500]}\n\n"
                        f"Intent Summary:"
                    )
                    resp = await chat_model.ainvoke(prompt)
                    summary = resp.content if isinstance(resp.content, str) else str(resp.content)
                    if summary:
                        intent = summary.strip()
                        is_synthesized = True
                except Exception as llm_err:
                    logger.debug(f"LLM commit intent synthesis skipped: {llm_err}")

            diff_summaries.append({
                "hash": h,
                "author": author,
                "date": date,
                "rawMessage": msg,
                "diffSnippet": diff_text[:1000],
                "intentSummary": intent,
                "isSynthesized": is_synthesized
            })
        except Exception as err:
            logger.warning(f"Error processing commit {commit.hexsha}: {err}")

    return diff_summaries
