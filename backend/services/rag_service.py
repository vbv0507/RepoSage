import os
import re
import ntpath
import logging
import uuid
from typing import Dict, Any, Callable, Optional
from git import Repo

from .ast_parser import scan_directory, parse_code_file, build_dependency_graph
from .git_archaeology import analyze_git_archaeology
from .chroma_service import (
    store_code_chunks, store_diff_summaries, search_codebase, get_repo_vector_stats,
    store_query_cache, find_semantic_query_match, clear_query_cache
)
from .redis_service import cache_service
from .llm_provider import get_chat_model

logger = logging.getLogger("rag_service")

WINDOWS_PATH = re.compile(r"^[a-zA-Z]:[\\\\/]")
UPLOAD_REPO_PREFIX = "upload://"


def _normalise_windows_path(path: str) -> str:
    """Return a comparison-safe, absolute Windows path without touching the host FS."""
    return ntpath.normpath(path).replace("/", "\\").rstrip("\\").casefold()


def _windows_path_with_case(path: str) -> str:
    """Normalize separators while preserving the casing needed by Linux mounts."""
    return ntpath.normpath(path).replace("/", "\\").rstrip("\\")


def _resolve_local_path(path: str) -> str:
    """Resolve a local path, including an optional Windows-host-to-container mapping.

    Docker containers cannot see arbitrary folders from the Windows host.  Compose
    mounts HOST_REPO_ROOT at /workspace and this function maps a path typed in the
    browser below that host root to the corresponding container path.
    """
    if WINDOWS_PATH.match(path) and os.name != "nt":
        host_root = os.getenv("HOST_REPO_ROOT", "").strip()
        mount_root = os.getenv("REPO_MOUNT_PATH", "/workspace")
        if not host_root:
            raise ValueError(
                "This server is running in Docker and cannot read a Windows path yet. "
                "Set HOST_REPO_ROOT to the host folder mounted at /workspace, then try again. "
                "For a hosted deployment, use a public GitHub URL instead."
            )

        source_for_mapping = _windows_path_with_case(path)
        root_for_mapping = _windows_path_with_case(host_root)
        source = source_for_mapping.casefold()
        root = root_for_mapping.casefold()
        if source != root and not source.startswith(root + "\\"):
            raise ValueError(
                f"The folder '{path}' is outside the configured HOST_REPO_ROOT ({host_root}). "
                "Choose a folder beneath that root or update HOST_REPO_ROOT."
            )
        # Compare case-insensitively (Windows behavior), but retain the input
        # casing because the destination filesystem in Docker is case-sensitive.
        relative = source_for_mapping[len(root_for_mapping):].lstrip("\\")
        resolved = os.path.abspath(os.path.join(mount_root, *relative.split("\\")))
    else:
        resolved = os.path.abspath(os.path.expanduser(path))

    if not os.path.isdir(resolved):
        raise ValueError(
            f"Local repository folder was not found or is not mounted: {path}. "
            f"Resolved server path: {resolved}"
        )
    if not os.access(resolved, os.R_OK):
        raise ValueError(f"Local repository folder is not readable by the server: {path}")
    return resolved


def resolve_uploaded_repo_path(repo_id: str) -> str:
    """Resolve an opaque browser-upload repository id without accepting paths."""
    try:
        upload_id = str(uuid.UUID(repo_id))
    except (ValueError, AttributeError) as exc:
        raise ValueError("The uploaded repository reference is invalid.") from exc

    upload_root = os.path.abspath(os.getenv("UPLOAD_REPO_ROOT", "/tmp/reposage_uploads"))
    resolved = os.path.join(upload_root, upload_id)
    if not os.path.isdir(resolved):
        raise ValueError("The uploaded repository is no longer available. Please upload it again.")
    return resolved

def resolve_repo_path(input_path: str, on_progress: Optional[Callable[[Dict[str, Any]], None]] = None) -> str:
    if not input_path:
        raise ValueError("Repository path or URL is required.")
    trimmed = input_path.strip()

    if trimmed.startswith(UPLOAD_REPO_PREFIX):
        return resolve_uploaded_repo_path(trimmed[len(UPLOAD_REPO_PREFIX):])

    is_remote = bool(re.match(r'^(https?://|git@)', trimmed, re.IGNORECASE))
    if not is_remote:
        return _resolve_local_path(trimmed)

    repo_name = trimmed.rstrip('/').split('/')[-1].replace('.git', '') or 'remote_repo'
    clone_base = os.path.abspath('./cloned_repos')
    os.makedirs(clone_base, exist_ok=True)
    target_dir = os.path.join(clone_base, repo_name)

    if not os.path.exists(target_dir):
        if on_progress:
            on_progress({"step": "cloning", "message": f"Cloning remote GitHub repository: {trimmed}..."})
        Repo.clone_from(trimmed, target_dir, depth=30)
        if on_progress:
            on_progress({"step": "cloned", "message": f"Successfully cloned {repo_name}."})
    else:
        if on_progress:
            on_progress({"step": "cloning", "message": f"Syncing repository: pulling latest commits for {repo_name}..."})
        try:
            repo = Repo(target_dir)
            origin = repo.remotes.origin
            origin.pull()
            if on_progress:
                on_progress({"step": "cloned", "message": f"Successfully updated {repo_name} to latest commit."})
        except Exception as e:
            logger.warning(f"Pull failed for {repo_name}, using existing clone: {e}")
            if on_progress:
                on_progress({"step": "cloned", "message": f"Using existing clone for {repo_name}."})

    return target_dir

def get_latest_commit(repo_path: str) -> Optional[str]:
    try:
        repo = Repo(repo_path)
        return repo.head.commit.hexsha
    except Exception:
        return None

async def ingest_codebase(
    repo_path: str,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    force_refresh: bool = False
) -> Dict[str, Any]:
    def notify(data):
        if on_progress:
            on_progress(data)

    current_commit = get_latest_commit(repo_path)

    # 1. Check if already ingested
    if not force_refresh:
        stats = await get_repo_vector_stats(repo_path)
        cached_graph = await cache_service.get(f"graph:{repo_path}")
        if stats.get("exists") and stats.get("count", 0) > 0 and cached_graph:
            notify({"step": "cached", "message": f"Repository vectors verified ({stats['count']} chunks). Serving instantly!"})
            notify({"step": "complete", "message": "Repository intelligence ready!"})
            return {
                "repoPath": repo_path,
                "cached": True,
                "fromCache": True,
                "chunksCount": stats["count"],
                "filesCount": stats.get("filesCount", 0),
                "gitDiffsCount": 0,
                "graphNodesCount": len(cached_graph.get("nodes", [])),
                "graphLinksCount": len(cached_graph.get("links", []))
            }

    # Clear existing semantic query cache on fresh/force re-ingestion
    await clear_query_cache(repo_path)

    # 2. File Discovery
    notify({"step": "scanning", "message": "Scanning directory tree and detecting programming languages..."})
    file_paths = scan_directory(repo_path)
    if not file_paths:
        raise ValueError(f"No parseable source code files discovered in: {repo_path}")

    notify({"step": "found_files", "message": f"Discovered {len(file_paths)} source files.", "count": len(file_paths)})

    # 3. AST Parsing
    notify({"step": "parsing", "message": f"Parsing AST structures for {len(file_paths)} files...", "totalFiles": len(file_paths)})
    parsed_files = []
    all_chunks = []

    for i, fp in enumerate(file_paths):
        p_file = parse_code_file(fp, repo_path)
        parsed_files.append(p_file)
        all_chunks.extend(p_file.get("chunks", []))
        if (i + 1) % 10 == 0 or i == len(file_paths) - 1:
            notify({"step": "parsing_progress", "current": i + 1, "total": len(file_paths)})

    # 4. Architectural Graph
    notify({"step": "graph", "message": "Building architectural dependency graph..."})
    graph = build_dependency_graph(parsed_files)
    await cache_service.set(f"graph:{repo_path}", graph, 86400)

    # 5. Store in ChromaDB reposage_code
    notify({"step": "storing_code", "message": f"Indexing and storing {len(all_chunks)} code blocks into vector database..."})
    await store_code_chunks(repo_path, all_chunks)

    # 6. Git Archaeology -> reposage_diffs
    notify({"step": "git_archaeology", "message": "Performing Git Archaeology on recent commits..."})
    diffs = await analyze_git_archaeology(repo_path, max_commits=15)
    if diffs:
        notify({"step": "embedding_git", "message": f"Indexing {len(diffs)} historical Git diffs into vector database..."})
        await store_diff_summaries(repo_path, diffs)

    notify({"step": "complete", "message": "Repository ingestion complete!"})

    return {
        "repoPath": repo_path,
        "filesCount": len(file_paths),
        "chunksCount": len(all_chunks),
        "gitDiffsCount": len(diffs),
        "graphNodesCount": len(graph.get("nodes", [])),
        "graphLinksCount": len(graph.get("links", []))
    }

async def query_codebase(repo_path: Optional[str], question: str, refresh: bool = False) -> Dict[str, Any]:
    if not question:
        raise ValueError("Question is required.")

    # Tier 1: Fast Exact Redis Cache Lookup
    cache_key = f"query:{repo_path}:{question.strip().lower()}"
    if not refresh:
        cached = await cache_service.get(cache_key)
        if cached and cached.get("answer") and len(cached["answer"]) > 200:
            logger.info(f"[Cache] ⚡ Returning exact match from Redis for: '{question}'")
            return {**cached, "fromCache": True, "cacheType": "exact_redis"}

        # Tier 2: Offline-Ready Semantic Vector Cache (ChromaDB all-MiniLM-L6-v2)
        semantic_match = await find_semantic_query_match(repo_path, question, threshold=0.85)
        if semantic_match and semantic_match.get("matched") and semantic_match.get("answer"):
            logger.info(
                f"[Semantic Cache] ⚡ Returning semantic match ({semantic_match['similarity']*100:.1f}%) "
                f"for '{question}' -> matched: '{semantic_match['matchedQuestion']}'"
            )
            return {
                "answer": semantic_match["answer"],
                "question": question,
                "matchedQuestion": semantic_match["matchedQuestion"],
                "similarity": semantic_match["similarity"],
                "fromCache": True,
                "semanticCache": True,
                "cacheType": "semantic_chromadb",
                "codeMatches": semantic_match.get("codeCitations", []),
                "diffMatches": semantic_match.get("gitCitations", []),
                "citations": [
                    f"{c.get('filePath')}:{c.get('startLine')}-{c.get('endLine')}"
                    for c in semantic_match.get("codeCitations", [])
                    if isinstance(c, dict) and c.get("filePath")
                ]
            }

    # 1. Dual-Vector Search (Current Code + Historical Diffs)
    matches = await search_codebase(repo_path=repo_path, question=question, top_k=5)
    code_matches = matches.get("codeMatches", [])
    diff_matches = matches.get("diffMatches", [])

    # 2. Dependency Graph Context
    graph_context = ""
    if repo_path:
        cached_graph = await cache_service.get(f"graph:{repo_path}")
        if cached_graph and cached_graph.get("links"):
            top_links = "\n".join(f"{l['source']} -> {l['target']}" for l in cached_graph["links"][:10])
            graph_context = f"Known Architecture Connections:\n{top_links}\n\n"

    # 3. Context Construction
    code_blocks_str = []
    citations = []
    for i, c in enumerate(code_matches):
        meta = c.get("metadata", {})
        fp = meta.get("filePath", "unknown")
        s = meta.get("startLine", 1)
        e = meta.get("endLine", 1)
        citations.append(f"{fp}:{s}-{e}")
        code_blocks_str.append(f"[Code Block {i+1}] File: {fp} (Lines {s}-{e}):\n```\n{c.get('content')}\n```")

    diffs_blocks_str = []
    for i, d in enumerate(diff_matches):
        meta = d.get("metadata", {})
        diffs_blocks_str.append(
            f"[Git Archaeology {i+1}] Commit: {meta.get('hash')} by {meta.get('author')} ({meta.get('date')}):\n"
            f"Intent Summary: {d.get('content')}"
        )

    code_context = "\n\n".join(code_blocks_str)
    diff_context = "\n\n".join(diffs_blocks_str)

    system_prompt = (
        "You are RepoSage, a Principal Software Architect AI specializing in legacy codebase intelligence and architectural decision tracing.\n\n"
        "Your goal is to answer the developer's question accurately, citing specific files, functions, line numbers, and historical git reasons.\n\n"
        f"Repository Context:\n{graph_context}"
        f"Retrieved Code Implementations:\n{code_context}\n\n"
        + (f"Retrieved Historical Git Changes (Why it was built this way):\n{diff_context}\n\n" if diff_context else "")
        + f"Developer Question: {question}\n\n"
        "Instructions:\n"
        "- Explain the architectural reason and technical flow.\n"
        "- Reference exact file names and line ranges when discussing code.\n"
        "- If historical diffs provide context on WHY a decision or change was made, highlight it under a '🏛️ Architectural Decision History' section.\n"
        "- Use clean Markdown format with code snippets where helpful.\n\n"
        "Answer:"
    )

    try:
        chat_model = get_chat_model(temperature=0.2)
        response = await chat_model.ainvoke(system_prompt)
        if isinstance(response.content, str):
            answer_text = response.content
        elif isinstance(response.content, list):
            answer_text = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in response.content)
        else:
            answer_text = str(response.content)
    except Exception as llm_error:
        logger.warning(f"[LLM] Cloud LLM unavailable ({llm_error}). Checking offline semantic fallback...")
        # Offline Resilience: Check if we have an approximate semantic match (>= 0.65 similarity)
        fallback_match = await find_semantic_query_match(repo_path, question, threshold=0.65)
        if fallback_match and fallback_match.get("answer"):
            logger.info(f"[Offline Mode] 🛡️ Recovered using offline semantic match: '{fallback_match['matchedQuestion']}'")
            return {
                "answer": (
                    f"> ⚡ **[Offline Mode Active]** Network connection to cloud LLM is offline. "
                    f"Showing nearest semantic match ({fallback_match['similarity']*100:.1f}% match to: *\"{fallback_match['matchedQuestion']}\"*):\n\n"
                    + fallback_match["answer"]
                ),
                "question": question,
                "matchedQuestion": fallback_match["matchedQuestion"],
                "similarity": fallback_match["similarity"],
                "fromCache": True,
                "semanticCache": True,
                "offlineFallback": True,
                "cacheType": "offline_semantic_fallback",
                "codeMatches": code_matches,
                "diffMatches": diff_matches,
                "citations": list(set(citations))
            }
        raise RuntimeError(
            f"RepoSage is currently offline and unable to reach the cloud LLM, and no semantically similar question "
            f"has been cached locally yet. (Original error: {llm_error})"
        )

    code_meta_list = [
        {
            "filePath": c.get("metadata", {}).get("filePath"),
            "name": c.get("metadata", {}).get("name"),
            "startLine": c.get("metadata", {}).get("startLine"),
            "endLine": c.get("metadata", {}).get("endLine"),
            "snippet": (c.get("content") or "")[:300]
        }
        for c in code_matches
    ]

    git_meta_list = [
        {
            "hash": d.get("metadata", {}).get("hash"),
            "author": d.get("metadata", {}).get("author"),
            "date": d.get("metadata", {}).get("date"),
            "summary": (d.get("content") or "")[:200]
        }
        for d in diff_matches
    ]

    result = {
        "answer": answer_text,
        "question": question,
        "codeMatches": code_matches,
        "diffMatches": diff_matches,
        "codeCitations": code_meta_list,
        "gitCitations": git_meta_list,
        "citations": list(set(citations))
    }

    # Cache in Redis (Fast Exact Tier)
    await cache_service.set(cache_key, result, 86400)

    # Cache in ChromaDB reposage_queries (Local Semantic Vector Tier)
    await store_query_cache(
        repo_path=repo_path,
        question=question,
        answer=answer_text,
        code_citations=code_meta_list,
        git_citations=git_meta_list
    )

    return result
