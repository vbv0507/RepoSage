import os
import re
import logging
from typing import Dict, Any, Callable, Optional
from git import Repo

from .ast_parser import scan_directory, parse_code_file, build_dependency_graph
from .git_archaeology import analyze_git_archaeology
from .chroma_service import store_code_chunks, store_diff_summaries, search_codebase, get_repo_vector_stats
from .redis_service import cache_service
from .llm_provider import get_chat_model

logger = logging.getLogger("rag_service")

def resolve_repo_path(input_path: str, on_progress: Optional[Callable[[Dict[str, Any]], None]] = None) -> str:
    if not input_path:
        raise ValueError("Repository path or URL is required.")
    trimmed = input_path.strip()

    is_remote = bool(re.match(r'^(https?://|git@)', trimmed, re.IGNORECASE))
    if not is_remote:
        return os.path.abspath(trimmed)

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
                "chunksCount": stats["count"],
                "filesCount": stats.get("filesCount", 0),
                "graphNodesCount": len(cached_graph.get("nodes", [])),
                "graphLinksCount": len(cached_graph.get("links", []))
            }

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

    cache_key = f"query:{repo_path}:{question.strip().lower()}"
    if not refresh:
        cached = await cache_service.get(cache_key)
        if cached and cached.get("answer") and len(cached["answer"]) > 200:
            return {**cached, "fromCache": True}

    # 1. Dual-Vector Search
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

    chat_model = get_chat_model(temperature=0.2)
    response = await chat_model.ainvoke(system_prompt)
    if isinstance(response.content, str):
        answer_text = response.content
    elif isinstance(response.content, list):
        answer_text = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in response.content)
    else:
        answer_text = str(response.content)

    result = {

        "answer": answer_text,
        "question": question,
        "codeMatches": code_matches,
        "diffMatches": diff_matches,
        "citations": list(set(citations))
    }

    await cache_service.set(cache_key, result, 86400)
    return result
