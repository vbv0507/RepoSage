import os
import re
import ntpath
import logging
import uuid
import hashlib
from typing import Dict, Any, Callable, Optional
from git import Repo

from .ast_parser import scan_directory_with_report, parse_code_file, build_dependency_graph
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
SEMANTIC_CACHE_DIRECT_THRESHOLD = 0.88
SEMANTIC_CACHE_OFFLINE_THRESHOLD = 0.80


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


def _index_id(file_paths: list[str], repo_path: str) -> str:
    """Content-address an index run so old vectors/answers cannot leak forward."""
    digest = hashlib.sha256()
    for file_path in sorted(file_paths):
        digest.update(os.path.relpath(file_path, repo_path).replace("\\", "/").encode())
        with open(file_path, "rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()[:16]


def _file_hint(question: str, report: Optional[Dict[str, Any]]) -> Optional[str]:
    """Map an explicitly named source file in a question to the indexed path."""
    if not report:
        return None
    question_lower = question.lower().replace("\\", "/")
    candidates = report.get("parsedFiles") or []
    direct = [path for path in candidates if path.lower() in question_lower]
    if direct:
        return max(direct, key=len)
    names = {os.path.basename(path).lower(): path for path in candidates}
    for name, path in names.items():
        if name in question_lower:
            return path
    return None


def _asks_for_signature(question: str) -> bool:
    lowered = question.lower()
    return any(term in lowered for term in ("signature", "parameters", "arguments", "function name", "method name", "function does", "internals"))

async def ingest_codebase(
    repo_path: str,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    force_refresh: bool = False
) -> Dict[str, Any]:
    def notify(data):
        if on_progress:
            on_progress(data)

    # 1. File discovery and content fingerprint. The old implementation
    # checked cache before observing current source content, allowing a pull
    # or local edit to keep serving an older index indefinitely.
    notify({"step": "scanning", "message": "Scanning directory tree and detecting programming languages..."})
    file_paths, ingestion_report = scan_directory_with_report(repo_path)
    if not file_paths:
        raise ValueError(f"No parseable source code files discovered in: {repo_path}")
    index_id = _index_id(file_paths, repo_path)
    cached_report = await cache_service.get(f"ingestion_report:{repo_path}")
    cached_graph = await cache_service.get(f"graph:{repo_path}")
    stats = await get_repo_vector_stats(repo_path, index_id)
    if not force_refresh and cached_report and cached_report.get("indexId") == index_id and stats.get("exists") and stats.get("count", 0) > 0 and cached_graph:
        notify({"step": "cached", "message": f"Repository vectors verified ({stats['count']} chunks, index {index_id}). Serving instantly!"})
        notify({"step": "complete", "message": "Repository intelligence ready!"})
        return {"repoPath": repo_path, "cached": True, "fromCache": True, "indexId": index_id, "chunksCount": stats["count"], "filesCount": stats.get("filesCount", 0), "gitDiffsCount": 0, "graphNodesCount": len(cached_graph.get("nodes", [])), "graphLinksCount": len(cached_graph.get("links", [])), "ingestionReport": cached_report}

    # Clear semantic answers before publishing the new run.
    await clear_query_cache(repo_path)

    notify({"step": "found_files", "message": f"Discovered {len(file_paths)} source files.", "count": len(file_paths)})

    # 3. AST Parsing
    notify({"step": "parsing", "message": f"Parsing AST structures for {len(file_paths)} files...", "totalFiles": len(file_paths)})
    parsed_files = []
    all_chunks = []

    for i, fp in enumerate(file_paths):
        p_file = parse_code_file(fp, repo_path)
        relative_path = p_file["filePath"]
        if p_file.get("parseStatus") == "read_error":
            ingestion_report["skippedFiles"].append({"path": relative_path, "reason": p_file["warnings"][0]})
        else:
            parsed_files.append(p_file)
            all_chunks.extend(p_file.get("chunks", []))
            if p_file.get("warnings"):
                ingestion_report.setdefault("fallbackFiles", []).append({"path": relative_path, "reason": "; ".join(p_file["warnings"])})
        if (i + 1) % 10 == 0 or i == len(file_paths) - 1:
            notify({"step": "parsing_progress", "current": i + 1, "total": len(file_paths)})

    # 4. Architectural Graph
    notify({"step": "graph", "message": "Building architectural dependency graph..."})
    graph = build_dependency_graph(parsed_files)
    await cache_service.set(f"graph:{repo_path}", graph, 86400)
    ingestion_report["parsedFiles"] = [item["filePath"] for item in parsed_files]
    ingestion_report["indexId"] = index_id
    ingestion_report["filesWithChunks"] = [item["filePath"] for item in parsed_files if item.get("chunks")]
    ingestion_report["summary"] = {
        "discovered": len(ingestion_report["discoveredFiles"]),
        "parsed": len(ingestion_report["parsedFiles"]),
        "fallback": len(ingestion_report.get("fallbackFiles", [])),
        "skipped": len(ingestion_report["skippedFiles"]),
        "skippedDirectories": len(ingestion_report["skippedDirectories"]),
        "truncated": ingestion_report["truncated"],
    }
    # 5. Store in ChromaDB reposage_code
    notify({"step": "storing_code", "message": f"Indexing and storing {len(all_chunks)} code blocks into vector database..."})
    storage_result = await store_code_chunks(repo_path, all_chunks, index_id)
    if storage_result.get("failedFiles"):
        ingestion_report["embeddingFailures"] = storage_result["failedFiles"]
        ingestion_report["skippedFiles"].extend(storage_result["failedFiles"])
        ingestion_report["truncated"] = True
        ingestion_report["summary"]["skipped"] = len(ingestion_report["skippedFiles"])
        ingestion_report["summary"]["embeddingFailures"] = len(storage_result["failedFiles"])
        ingestion_report["summary"]["truncated"] = True
        notify({"step": "warning", "message": f"{len(storage_result['failedFiles'])} source files could not be embedded; see Index coverage report."})
    await cache_service.set(f"ingestion_report:{repo_path}", ingestion_report, 86400)

    # 6. Git Archaeology -> reposage_diffs
    notify({"step": "git_archaeology", "message": "Performing Git Archaeology on recent commits..."})
    diffs = await analyze_git_archaeology(repo_path, max_commits=15)
    if diffs:
        notify({"step": "embedding_git", "message": f"Indexing {len(diffs)} historical Git diffs into vector database..."})
        await store_diff_summaries(repo_path, diffs, index_id)

    notify({"step": "complete", "message": "Repository ingestion complete!"})

    return {
        "repoPath": repo_path,
        "indexId": index_id,
        "filesCount": len(file_paths),
        "chunksCount": len(all_chunks),
        "gitDiffsCount": len(diffs),
        "graphNodesCount": len(graph.get("nodes", [])),
        "graphLinksCount": len(graph.get("links", [])),
        "ingestionReport": ingestion_report
    }


def _build_coverage_context(report: Optional[Dict[str, Any]]) -> str:
    """Compact file inventory supplied to the LLM as evidence of what was indexed."""
    if not report:
        return "Index completeness metadata is unavailable. Do not make claims about missing files or modules."
    files = report.get("parsedFiles") or report.get("discoveredFiles") or []
    modules: Dict[str, list[str]] = {}
    for file_path in files:
        directory, _, filename = file_path.rpartition("/")
        modules.setdefault(directory or ".", []).append(filename)
    module_lines = []
    for directory in sorted(modules)[:150]:
        names = ", ".join(sorted(modules[directory])[:12])
        suffix = "…" if len(modules[directory]) > 12 else ""
        module_lines.append(f"- {directory}/: {names}{suffix}")
    summary = report.get("summary", {})
    limits = report.get("limits", {})
    completeness = "INCOMPLETE" if report.get("truncated") else "complete within configured limits"
    return (
        f"Index coverage is {completeness}: {summary.get('parsed', len(files))} parsed files, "
        f"{summary.get('skipped', 0)} skipped files, limit {limits.get('maxSourceFiles', 'unknown')} files.\n"
        "Indexed module/file inventory:\n" + "\n".join(module_lines)
    )

async def query_codebase(repo_path: Optional[str], question: str, refresh: bool = False) -> Dict[str, Any]:
    if not question:
        raise ValueError("Question is required.")

    report = await cache_service.get(f"ingestion_report:{repo_path}") if repo_path else None
    index_id = report.get("indexId") if report else None
    # Tier 1: Fast Exact Redis Cache Lookup
    # Versioned key avoids returning pre-trust-calibration cached answers.
    cache_key = f"query:v3:{repo_path}:{index_id}:{question.strip().lower()}"
    if not refresh:
        cached = await cache_service.get(cache_key)
        if cached and cached.get("answer") and len(cached["answer"]) > 200:
            logger.info(f"[Cache] ⚡ Returning exact match from Redis for: '{question}'")
            return {**cached, "fromCache": True, "cacheType": "exact_redis"}

        # Tier 2: Offline-Ready Semantic Vector Cache (ChromaDB all-MiniLM-L6-v2)
        semantic_match = await find_semantic_query_match(f"{repo_path}:{index_id}", question, threshold=SEMANTIC_CACHE_DIRECT_THRESHOLD)
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
    file_path_hint = _file_hint(question, report)
    matches = await search_codebase(repo_path=repo_path, question=question, top_k=5, index_id=index_id, file_path_hint=file_path_hint)
    code_matches = matches.get("codeMatches", [])
    diff_matches = matches.get("diffMatches", [])

    # 2. Dependency Graph Context
    graph_context = ""
    coverage_context = ""
    if repo_path:
        cached_graph = await cache_service.get(f"graph:{repo_path}")
        coverage_context = _build_coverage_context(report)
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

    structural_evidence = any(
        match.get("metadata", {}).get("filePath") == file_path_hint and match.get("metadata", {}).get("type") in {"function", "arrow_function", "class"}
        for match in code_matches
    )
    if file_path_hint and _asks_for_signature(question) and not structural_evidence:
        return {
            "answer": f"I can confirm `{file_path_hint}` exists in the indexed repository, but I do not have its function-level AST content in the current retrieval results. I can't state its actual function signatures from this context.",
            "question": question, "codeMatches": code_matches, "diffMatches": diff_matches,
            "signatureEvidenceMissing": True,
            "citations": list(set(citations))
        }

    system_prompt = (
        "You are RepoSage, a Principal Software Architect AI specializing in legacy codebase intelligence and architectural decision tracing.\n\n"
        "Your goal is to answer the developer's question accurately, citing specific files, functions, line numbers, and historical git reasons.\n\n"
        f"Repository Context:\n{graph_context}\n{coverage_context}\n\n"
        f"Retrieved Code Implementations:\n{code_context}\n\n"
        + (f"Retrieved Historical Git Changes (Why it was built this way):\n{diff_context}\n\n" if diff_context else "")
        + f"Developer Question: {question}\n\n"
        "Instructions:\n"
        "- Explain the architectural reason and technical flow.\n"
        "- Reference exact file names and line ranges when discussing code.\n"
        "- Absence from retrieved snippets is NOT evidence that a component does not exist. Never state that a module/file/component is absent as a fact unless the indexed file inventory directly proves it was excluded and you explain that limitation. If evidence is incomplete, say exactly: 'I found no direct evidence in the currently indexed context; this does not prove the component is absent.'\n"
        "- When the inventory lists a relevant module but snippets were not retrieved, acknowledge the module exists in the index and avoid inventing its implementation details.\n"
        "- Do not state a function name, parameter name, or signature unless the exact declaration is present verbatim in Retrieved Code Implementations. If structural code for a named file is unavailable, state that you cannot confirm its actual signature.\n"
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
        fallback_match = await find_semantic_query_match(f"{repo_path}:{index_id}", question, threshold=SEMANTIC_CACHE_OFFLINE_THRESHOLD)
        if fallback_match and fallback_match.get("matched") and fallback_match.get("answer"):
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
        return {
            "answer": "## No confident answer available\n\nRepoSage could not reach the live LLM, and no cached answer met the 80% similarity safety threshold for this question. It will not show a loosely related answer as if it were yours. Please retry when the LLM is available.",
            "question": question,
            "fromCache": False,
            "offlineNoConfidentAnswer": True,
            "cacheType": "offline_no_confident_match",
            "codeMatches": code_matches,
            "diffMatches": diff_matches,
            "citations": list(set(citations))
        }

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
        repo_path=f"{repo_path}:{index_id}",
        question=question,
        answer=answer_text,
        code_citations=code_meta_list,
        git_citations=git_meta_list
    )

    return result
