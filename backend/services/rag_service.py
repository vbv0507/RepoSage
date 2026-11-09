import os
import re
import ntpath
import logging
import uuid
import hashlib
import threading
import asyncio
import socket
import ipaddress
import urllib.parse
from typing import Dict, Any, Callable, Optional, AsyncGenerator, List
from git import Repo

from .ast_parser import scan_directory_with_report, parse_code_file, build_dependency_graph
from .git_archaeology import analyze_git_archaeology
from .chroma_service import (
    store_code_chunks, store_diff_summaries, store_file_profiles, find_relevant_files, search_codebase, get_repo_vector_stats,
    store_query_cache, find_semantic_query_match, clear_query_cache, delete_repo_file_vectors
)
from .cache_service import cache_service
from .llm_provider import get_chat_model
from .runtime_config import semantic_cache_enabled


logger = logging.getLogger("rag_service")

WINDOWS_PATH = re.compile(r"^[a-zA-Z]:[\\\\/]")
UPLOAD_REPO_PREFIX = "upload://"
CLONED_REPO_ROOT = os.getenv("CLONED_REPO_ROOT", "/tmp/reposage_clones")
MAX_CHUNKS_PER_REPO = int(os.getenv("MAX_CHUNKS_PER_REPO", "500"))
MAX_PROMPT_CONTEXT_CHARS = int(os.getenv("MAX_PROMPT_CONTEXT_CHARS", "30000"))
SEMANTIC_CACHE_DIRECT_THRESHOLD = 0.88
SEMANTIC_CACHE_OFFLINE_THRESHOLD = 0.80
CONFIDENCE_HIGH_SIMILARITY_THRESHOLD = 0.80
_index_locks: Dict[str, threading.Lock] = {}
_index_locks_guard = threading.Lock()


# Keep semantic-answer caching fully inactive on the Render free plan. Code
# retrieval remains available through the normal Chroma code collections.
if not semantic_cache_enabled():
    async def find_semantic_query_match(*args, **kwargs):
        return None

    async def store_query_cache(*args, **kwargs):
        return None

    async def clear_query_cache(*args, **kwargs):
        return None


def compute_confidence_level(
    code_matches: Optional[List[Dict[str, Any]]] = None,
    signature_evidence_missing: bool = False,
    offline_no_confident_answer: bool = False,
    threshold: float = CONFIDENCE_HIGH_SIMILARITY_THRESHOLD,
    min_close_matches: int = 3
) -> str:
    """
    Computes answer confidence level: 'high', 'medium', or 'low'.
    - 'high': at least min_close_matches (3) with similarity (1 - distance) >= threshold (0.80).
    - 'medium': 1-2 matches, or matches present but similarity below high cutoff.
    - 'low': 0 matches, or signature-evidence-missing, or offline-no-confident-answer.
    """
    if signature_evidence_missing or offline_no_confident_answer:
        return "low"
    if not code_matches:
        return "low"

    close_matches = 0
    for match in code_matches:
        dist = match.get("distance")
        if dist is not None:
            try:
                sim = max(0.0, 1.0 - float(dist))
                if sim >= threshold:
                    close_matches += 1
            except (ValueError, TypeError):
                pass

    if close_matches >= min_close_matches:
        return "high"

    return "medium"


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

def validate_remote_git_url(url: str) -> None:
    """Validate remote git repository URL against SSRF and private network access."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ValueError(f"Insecure or unsupported URL scheme '{parsed.scheme}'. Only https:// repository URLs are allowed.")
    
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid repository URL: missing hostname.")
    
    # Optional host allowlist via environment variable
    allowed_hosts_env = os.getenv("ALLOWED_GIT_HOSTS", "").strip()
    if allowed_hosts_env:
        allowed_hosts = {h.strip().lower() for h in allowed_hosts_env.split(",") if h.strip()}
        if hostname.lower() not in allowed_hosts:
            raise ValueError(f"Repository host '{hostname}' is not in the allowed hosts list ({', '.join(sorted(allowed_hosts))}).")

    # Resolve hostname to IP addresses and check for private / loopback / link-local addresses
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve repository hostname '{hostname}': {exc}")
    
    if not addr_infos:
        raise ValueError(f"No IP addresses resolved for hostname '{hostname}'.")

    for item in addr_infos:
        ip_str = item[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if (
                ip.is_loopback or
                ip.is_private or
                ip.is_link_local or
                ip.is_reserved or
                ip.is_multicast or
                ip.is_unspecified
            ):
                raise ValueError(f"Repository URL resolves to private or restricted IP address: {ip_str}")
        except ValueError as err:
            raise ValueError(f"Invalid IP address resolved for repository: {err}")


def resolve_repo_path(
    input_path: str,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    clone_depth: int = 100,
) -> str:
    if not input_path:
        raise ValueError("Repository path or URL is required.")
    trimmed = input_path.strip()

    if trimmed.startswith(UPLOAD_REPO_PREFIX):
        return resolve_uploaded_repo_path(trimmed[len(UPLOAD_REPO_PREFIX):])

    # Check for insecure or SSH schemes first
    if trimmed.lower().startswith("http://") or trimmed.lower().startswith("git@"):
        raise ValueError("Insecure or unsupported repository URL scheme. Only https:// repository URLs are permitted.")

    is_remote = bool(re.match(r'^https://', trimmed, re.IGNORECASE))
    if not is_remote:
        return _resolve_local_path(trimmed)

    # Validate remote HTTPS URL against SSRF
    validate_remote_git_url(trimmed)

    repo_name = trimmed.rstrip('/').split('/')[-1].replace('.git', '') or 'remote_repo'
    clone_base = os.path.abspath(CLONED_REPO_ROOT)
    os.makedirs(clone_base, exist_ok=True)
    target_dir = os.path.join(clone_base, repo_name)

    if not os.path.exists(target_dir):
        if on_progress:
            on_progress({"step": "cloning", "message": f"Cloning remote GitHub repository: {trimmed}..."})
        Repo.clone_from(trimmed, target_dir, depth=clone_depth)
        if on_progress:
            on_progress({"step": "cloned", "message": f"Successfully cloned {repo_name}."})
    else:
        if on_progress:
            on_progress({"step": "cloning", "message": f"Syncing repository: pulling latest commits for {repo_name}..."})
        try:
            repo = Repo(target_dir)
            origin = repo.remotes.origin
            origin.fetch(depth=clone_depth)
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


def _compute_file_hash(file_path: str) -> str:
    digest = hashlib.sha256()
    try:
        with open(file_path, "rb") as source:
            while chunk := source.read(65536):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def _file_hints(question: str, report: Optional[Dict[str, Any]]) -> List[str]:
    """Map explicitly named source files in a question to indexed paths."""
    if not report:
        return []
    question_lower = question.lower().replace("\\", "/")
    candidates = report.get("parsedFiles") or []
    return list(dict.fromkeys(
        path for path in candidates
        if path.lower() in question_lower
        or os.path.basename(path).lower() in question_lower
    ))


def _topic_file_hints(question: str, report: Optional[Dict[str, Any]]) -> List[str]:
    """Select bounded implementation files for architecture-topic questions."""
    if not report:
        return []
    question_lower = question.lower().replace("\\", "/")
    candidates = report.get("parsedFiles") or []
    hints = []
    topic_patterns = (
        (r"\b(runtime|active|actual|configuration|config|settings|yaml|environment)\b",
         ("config/", "settings.py", ".yaml", ".yml", ".env")),
        (r"\b(retriev\w*|embedding\w*|chunk\w*|faiss|vector\w*|similarity|top.?k)\b",
         ("retrieval/", "embed", "chunk", "vector", "config/")),
        (r"\b(rerank\w*|cross.?encoder)\b",
         ("rerank", "retrieval/pipeline")),
        (r"\b(route|middleware|controller|cloudinary|upload|express)\b",
         ("routes/", "middleware/", "controllers/", "cloudinary", "ai.service")),
        (r"\b(vision|image|multimodal)\b",
         ("vision/", "image", "chat.controller", "ai.service")),
        (r"\b(prompt|llm|generation|sanitiz\w*|model)\b",
         ("generation/", "prompt", "sanitize", "model.py", "llm")),
        (r"\b(memory|conversation|history|session)\b",
         ("memory", "conversation", "session")),
    )
    for pattern, path_fragments in topic_patterns:
        if re.search(pattern, question_lower):
            hints.extend(
                path for path in candidates
                if any(fragment in path.lower() for fragment in path_fragments)
            )
    return list(dict.fromkeys(hints))[:12]


def _file_hint(question: str, report: Optional[Dict[str, Any]]) -> Optional[str]:
    """Return the longest explicitly named source file for compatibility."""
    hints = _file_hints(question, report)
    return max(hints, key=len) if hints else None


def _focused_file_matches(repo_path: Optional[str], file_paths: List[str]) -> List[Dict[str, Any]]:
    """Read a small set of explicitly named indexed files for exact grounding."""
    if not repo_path or not file_paths:
        return []

    root = os.path.abspath(repo_path)
    matches = []
    for relative_path in file_paths[:8]:
        full_path = os.path.abspath(os.path.join(root, relative_path))
        if os.path.commonpath([root, full_path]) != root or not os.path.isfile(full_path):
            continue
        parsed = parse_code_file(full_path, root)
        for chunk in parsed.get("chunks", [])[:40]:
            matches.append({
                "type": "code",
                "content": chunk.get("code", ""),
                "metadata": {
                    "filePath": chunk.get("filePath", relative_path),
                    "type": chunk.get("type", "block"),
                    "name": chunk.get("name"),
                    "startLine": chunk.get("startLine", 1),
                    "endLine": chunk.get("endLine", 1),
                },
                "distance": 0.0,
            })
    return matches


def _usage_identifiers(question: str) -> List[str]:
    if not re.search(r"\b(unused|dead|active|used|usage|reference|imported|enforc)", question, re.IGNORECASE):
        return []
    identifiers = re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", question)
    identifiers.extend(re.findall(
        r"\b(?:unused|dead|active|used|usage|reference|imported|enforc\w*)"
        r"\s+(?:code|symbol|function|field|schema|variable|module)?\s*"
        r"`?([A-Za-z_][A-Za-z0-9_]*)`?",
        question,
        re.IGNORECASE,
    ))
    return list(dict.fromkeys(identifiers))[:3]


def _bounded_context(text: str, limit: int = MAX_PROMPT_CONTEXT_CHARS) -> str:
    """Keep retrieved evidence within the model/document context budget."""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[Additional retrieved context omitted due to context limit.]"


def _reference_matches(
    repo_path: Optional[str],
    report: Optional[Dict[str, Any]],
    question: str,
) -> List[Dict[str, Any]]:
    """Find bounded, exact symbol references for usage questions."""
    identifiers = _usage_identifiers(question)
    if not repo_path or not report or not identifiers:
        return []

    root = os.path.abspath(repo_path)
    matches = []
    for relative_path in (report.get("parsedFiles") or [])[:200]:
        full_path = os.path.abspath(os.path.join(root, relative_path))
        if os.path.commonpath([root, full_path]) != root or not os.path.isfile(full_path):
            continue
        try:
            with open(full_path, encoding="utf-8", errors="ignore") as source:
                for line_number, line in enumerate(source, 1):
                    if any(re.search(rf"\b{re.escape(identifier)}\b", line) for identifier in identifiers):
                        matches.append({
                            "type": "reference",
                            "content": line.strip(),
                            "metadata": {
                                "filePath": relative_path,
                                "type": "reference",
                                "name": next(
                                    identifier for identifier in identifiers
                                    if re.search(rf"\b{re.escape(identifier)}\b", line)
                                ),
                                "startLine": line_number,
                                "endLine": line_number,
                            },
                            "distance": 0.0,
                        })
        except OSError:
            continue
    return matches[:80]


def _asks_for_signature(question: str) -> bool:
    lowered = question.lower()
    return any(term in lowered for term in ("signature", "parameters", "arguments", "function name", "method name", "function does", "internals"))

def _index_lock(repo_path: str) -> threading.Lock:
    with _index_locks_guard:
        return _index_locks.setdefault(os.path.abspath(repo_path), threading.Lock())


async def ingest_codebase(
    repo_path: str,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    force_refresh: bool = False,
    max_source_files: Optional[int] = None,
) -> Dict[str, Any]:
    """Serialize indexing work for each repository across HTTP and startup tasks."""
    lock = _index_lock(repo_path)
    if lock.locked() and on_progress:
        on_progress({"step": "waiting", "message": "An index run for this repository is already active; waiting for it to finish."})
    await asyncio.to_thread(lock.acquire)
    try:
        return await _ingest_codebase_unlocked(repo_path, on_progress, force_refresh, max_source_files)
    finally:
        lock.release()


async def _ingest_codebase_unlocked(
    repo_path: str,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    force_refresh: bool = False,
    max_source_files: Optional[int] = None,
) -> Dict[str, Any]:
    def notify(data):
        if on_progress:
            on_progress(data)

    notify({"step": "scanning", "message": "Scanning directory tree and detecting programming languages..."})
    file_paths, ingestion_report = scan_directory_with_report(repo_path, max_files=max_source_files or 2000)
    non_empty_paths = []
    for file_path in file_paths:
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as source:
                non_empty_lines = sum(1 for line in source if line.strip())
        except OSError:
            non_empty_lines = 5
        # Small implementation files are valid source. Only discard the common
        # empty-package boilerplate that adds no retrieval value.
        if os.path.basename(file_path) == "__init__.py" and non_empty_lines < 5:
            ingestion_report["skippedFiles"].append({
                "path": os.path.relpath(file_path, repo_path).replace("\\", "/"),
                "reason": "near_empty_source",
            })
            continue
        non_empty_paths.append(file_path)
    file_paths = non_empty_paths
    if not file_paths:
        raise ValueError(f"No parseable source code files discovered in: {repo_path}")

    from .chroma_service import get_embedding_status
    embedding_start = get_embedding_status()
    logger.info("Starting index for %s with %s embeddings", repo_path, embedding_start["backend"])
    notify({"step": "embedding_backend", "backend": embedding_start["backend"], "message": f"Embedding backend: {embedding_start['backend']}"})

    index_id = _index_id(file_paths, repo_path)
    current_hashes = {
        os.path.relpath(fp, repo_path).replace("\\", "/"): _compute_file_hash(fp)
        for fp in file_paths
    }

    cached_report = await cache_service.get(f"ingestion_report:{repo_path}")
    cached_graph = await cache_service.get(f"graph:{repo_path}")
    stored_hashes = await cache_service.get(f"file_hashes:{repo_path}") or {}
    stats = await get_repo_vector_stats(repo_path)

    # Calculate per-file delta
    added = {p for p in current_hashes if p not in stored_hashes}
    modified = {p for p in current_hashes if p in stored_hashes and current_hashes[p] != stored_hashes[p]}
    removed = {p for p in stored_hashes if p not in current_hashes}
    unchanged = {p for p in current_hashes if p in stored_hashes and current_hashes[p] == stored_hashes[p]}

    if not force_refresh and not added and not modified and not removed and cached_report and stats.get("exists") and stats.get("count", 0) > 0 and cached_graph:
        notify({"step": "cached", "message": f"Repository vectors verified ({stats['count']} chunks, index {index_id}). Serving instantly!"})
        notify({"step": "complete", "message": "Repository intelligence ready!"})
        return {
            "repoPath": repo_path,
            "cached": True,
            "fromCache": True,
            "indexId": index_id,
            "chunksCount": stats["count"],
            "filesCount": len(file_paths),
            "gitDiffsCount": 0,
            "graphNodesCount": len(cached_graph.get("nodes", [])),
            "graphLinksCount": len(cached_graph.get("links", [])),
            "ingestionReport": cached_report
        }

    # Clear semantic answers before publishing new index run
    await clear_query_cache(repo_path)

    is_incremental = not force_refresh and bool(stored_hashes)
    if is_incremental:
        if removed:
            notify({"step": "incremental_clean", "message": f"Pruning {len(removed)} deleted files from vector index..."})
            await delete_repo_file_vectors(repo_path, list(removed))
        if modified:
            notify({"step": "incremental_clean", "message": f"Clearing vectors for {len(modified)} modified files..."})
            await delete_repo_file_vectors(repo_path, list(modified))
        files_to_process = [fp for fp in file_paths if os.path.relpath(fp, repo_path).replace("\\", "/") in (added | modified)]
        clear_prior = False
    else:
        files_to_process = file_paths
        clear_prior = True

    notify({"step": "found_files", "message": f"Discovered {len(file_paths)} source files ({len(files_to_process)} to index).", "count": len(file_paths), "deltaCount": len(files_to_process)})

    # AST Parsing
    notify({"step": "parsing", "message": f"Parsing AST structures for {len(files_to_process)} files...", "totalFiles": len(files_to_process)})
    parsed_files = []
    new_chunks = []

    for i, fp in enumerate(files_to_process):
        p_file = parse_code_file(fp, repo_path)
        relative_path = p_file["filePath"]
        if p_file.get("parseStatus") == "read_error":
            ingestion_report["skippedFiles"].append({"path": relative_path, "reason": p_file["warnings"][0]})
        else:
            parsed_files.append(p_file)
            new_chunks.extend(p_file.get("chunks", []))
            if p_file.get("warnings"):
                ingestion_report.setdefault("fallbackFiles", []).append({"path": relative_path, "reason": "; ".join(p_file["warnings"])})
        if (i + 1) % 10 == 0 or i == len(files_to_process) - 1:
            notify({"step": "parsing_progress", "current": i + 1, "total": len(files_to_process)})

    # Build dependency graph
    notify({"step": "graph", "message": "Building architectural dependency graph..."})
    all_current_parsed = parsed_files if not is_incremental else [parse_code_file(fp, repo_path) for fp in file_paths]
    graph = build_dependency_graph(all_current_parsed)
    await cache_service.set(f"graph:{repo_path}", graph, 86400)

    # Ingestion report reflecting full current file set
    if is_incremental and cached_report:
        old_parsed = [f for f in cached_report.get("parsedFiles", []) if f not in removed and f not in modified]
        all_parsed_paths = sorted(list(set(old_parsed + [item["filePath"] for item in parsed_files])))
        old_chunks_paths = [f for f in cached_report.get("filesWithChunks", []) if f not in removed and f not in modified]
        new_chunks_paths = [item["filePath"] for item in parsed_files if item.get("chunks")]
        all_files_with_chunks = sorted(list(set(old_chunks_paths + new_chunks_paths)))

        old_fallbacks = [f for f in cached_report.get("fallbackFiles", []) if f.get("path") not in removed and f.get("path") not in modified]
        current_fb_paths = {f["path"] for f in ingestion_report.get("fallbackFiles", [])}
        for fb in old_fallbacks:
            if fb.get("path") not in current_fb_paths:
                ingestion_report.setdefault("fallbackFiles", []).append(fb)
    else:
        all_parsed_paths = [item["filePath"] for item in parsed_files]
        all_files_with_chunks = [item["filePath"] for item in parsed_files if item.get("chunks")]

    ingestion_report["parsedFiles"] = all_parsed_paths
    ingestion_report["indexId"] = index_id
    ingestion_report["filesWithChunks"] = all_files_with_chunks
    ingestion_report["incremental"] = {
        "added": len(added),
        "modified": len(modified),
        "removed": len(removed),
        "unchanged": len(unchanged)
    }
    ingestion_report["summary"] = {
        "discovered": len(ingestion_report["discoveredFiles"]),
        "parsed": len(ingestion_report["parsedFiles"]),
        "fallback": len(ingestion_report.get("fallbackFiles", [])),
        "skipped": len(ingestion_report["skippedFiles"]),
        "skippedDirectories": len(ingestion_report["skippedDirectories"]),
        "truncated": ingestion_report["truncated"],
    }

    if len(new_chunks) > MAX_CHUNKS_PER_REPO:
        new_chunks = new_chunks[:MAX_CHUNKS_PER_REPO]
        ingestion_report["truncated"] = True
        ingestion_report["chunkLimit"] = MAX_CHUNKS_PER_REPO
        ingestion_report.setdefault("warnings", []).append(
            f"Code chunks were capped at {MAX_CHUNKS_PER_REPO} to protect embedding quota."
        )

    embedding_degraded = False
    # Store in ChromaDB reposage_code
    if new_chunks:
        notify({"step": "storing_code", "message": f"Indexing and storing {len(new_chunks)} code blocks into vector database..."})
        storage_result = await store_code_chunks(repo_path, new_chunks, index_id, clear_prior=clear_prior, on_progress=notify)
        if storage_result.get("failedFiles"):
            ingestion_report["embeddingFailures"] = storage_result["failedFiles"]
            ingestion_report["skippedFiles"].extend(storage_result["failedFiles"])
            ingestion_report["truncated"] = True
            ingestion_report["summary"]["skipped"] = len(ingestion_report["skippedFiles"])
            ingestion_report["summary"]["embeddingFailures"] = len(storage_result["failedFiles"])
            ingestion_report["summary"]["truncated"] = True
            ingestion_report["embeddingStatus"] = "degraded"
            embedding_degraded = True
            ingestion_report.setdefault("warnings", []).append(
                "Some code vectors were not stored because the configured embedding backend was unavailable."
            )
            notify({"step": "warning", "message": f"{len(storage_result['failedFiles'])} source files could not be embedded; see Index coverage report."})
    elif clear_prior:
        await store_code_chunks(repo_path, [], index_id, clear_prior=True)

    await cache_service.set(f"ingestion_report:{repo_path}", ingestion_report, 86400)
    await cache_service.set(f"file_hashes:{repo_path}", current_hashes, 86400 * 30)

    if parsed_files and not embedding_degraded:
        indexed_files = {chunk.get("filePath") for chunk in new_chunks}
        await store_file_profiles(
            repo_path,
            [parsed for parsed in parsed_files if parsed.get("filePath") in indexed_files],
            index_id,
            clear_prior=clear_prior,
        )

    # Git Archaeology
    notify({"step": "git_archaeology", "message": "Performing Git Archaeology on recent commits..."})
    diffs = await analyze_git_archaeology(repo_path, max_commits=15)
    if diffs and not embedding_degraded:
        notify({"step": "embedding_git", "message": f"Indexing {len(diffs)} historical Git diffs into vector database..."})
        await store_diff_summaries(repo_path, diffs, index_id)

    # Final stats reflecting full current file set
    updated_stats = await get_repo_vector_stats(repo_path)
    total_chunks = updated_stats.get("count", len(new_chunks))

    notify({"step": "complete", "message": "Repository ingestion complete!"})

    embedding_status = get_embedding_status()
    logger.info("Index complete for %s using %s embeddings: %s successful calls, %s failed calls", repo_path, embedding_status["backend"], embedding_status["successfulCalls"], embedding_status["failedCalls"])
    return {
        "repoPath": repo_path,
        "indexId": index_id,
        "filesCount": len(file_paths),
        "chunksCount": total_chunks,
        "gitDiffsCount": len(diffs) if diffs else 0,
        "graphNodesCount": len(graph.get("nodes", [])),
        "graphLinksCount": len(graph.get("links", [])),
        "ingestionReport": ingestion_report,
        "embedding": embedding_status,
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

def _build_cache_key(repo_path: Optional[str], index_id: Optional[str], question: str) -> str:
    """Build canonical exact-cache key versioned with content fingerprint."""
    clean_q = (question or "").strip().lower()
    return f"query:v3:{repo_path}:{index_id}:{clean_q}"


def _build_semantic_cache_scope(repo_path: Optional[str], index_id: Optional[str]) -> str:
    """Build canonical ChromaDB semantic-cache repoPath scope string."""
    if repo_path and index_id:
        return f"{repo_path}:{index_id}"
    return repo_path or "global"


TASK_ORIENTED_PATTERN = re.compile(
    r"\b("
    r"how\s+(do|can)\s+i\s+(add|create|implement|build|wire)|"
    r"where\s+(do|can)\s+i\s+(add|create|implement|put|wire)|"
    r"where\s+to\s+(add|create|implement|put)|"
    r"i\s+(need|want)\s+to\s+(add|create|implement|build)|"
    r"add\s+a\s+new|"
    r"create\s+a(\s+new)?|"
    r"implement|"
    r"steps\s+to\s+(add|create|implement|build)"
    r")\b",
    re.IGNORECASE
)


def _is_task_oriented_question(question: str) -> bool:
    """Classify whether a developer query is asking for change steps/where to add a feature.

    NOTE: Lightweight keyword/regex classifier used to avoid an extra LLM round-trip latency.
    May misclassify ambiguous conversational queries.
    """
    if not question:
        return False
    return bool(TASK_ORIENTED_PATTERN.search(question.strip()))


async def find_analogous_feature(
    repo_path: Optional[str],
    index_id: Optional[str],
    question: str
) -> Dict[str, Any]:
    """
    Locates an analogous existing feature matching the task's shape:
    1. Uses file-profile routing (find_relevant_files) to locate candidate files.
    2. Traces dependency graph edges to find connected route/service/frontend files.
    3. Retrieves code chunks for the identified template files using search_codebase focused-file retrieval.
    """
    candidate_files: List[str] = []

    # 1. Profile routing for matching shape (e.g. endpoint, route, handler)
    if repo_path and index_id:
        try:
            profile_matches = await find_relevant_files(repo_path, index_id, question, top_k=3)
            candidate_files = [m["filePath"] for m in profile_matches if m.get("filePath")]
        except Exception as exc:
            logger.warning(f"[Guided Change] Profile routing error: {exc}")

    # Fallback to code search if no profile candidates
    if not candidate_files:
        try:
            search_res = await search_codebase(repo_path=repo_path, question=question, top_k=4, index_id=index_id)
            candidate_files = list(dict.fromkeys(
                m["metadata"]["filePath"]
                for m in search_res.get("codeMatches", [])
                if m.get("metadata", {}).get("filePath")
            ))
        except Exception as exc:
            logger.warning(f"[Guided Change] Fallback code search error: {exc}")

    # 2. Dependency Graph Tracing
    connected_files: List[str] = []
    connected_links: List[str] = []

    if repo_path:
        cached_graph = await cache_service.get(f"graph:{repo_path}")
        if cached_graph and cached_graph.get("links"):
            links = cached_graph["links"]
            for cand in candidate_files:
                if cand not in connected_files:
                    connected_files.append(cand)
                # Outgoing & incoming connections
                for link in links:
                    src = link.get("source")
                    tgt = link.get("target")
                    if src == cand and tgt and tgt not in connected_files:
                        connected_files.append(tgt)
                        connected_links.append(f"{src} -> {tgt}")
                    elif tgt == cand and src and src not in connected_files:
                        connected_files.append(src)
                        connected_links.append(f"{src} -> {tgt}")

    template_files = connected_files[:4] if connected_files else candidate_files[:3]

    # 3. Retrieve focused code chunks for template files
    matches = await search_codebase(
        repo_path=repo_path,
        question=question,
        top_k=5,
        index_id=index_id,
        file_path_hints=template_files if template_files else None
    )

    return {
        "templateFiles": template_files,
        "codeMatches": matches.get("codeMatches", []),
        "diffMatches": matches.get("diffMatches", []),
        "connectedLinks": connected_links
    }


def _parse_guided_steps(text: str, template_files: List[str]) -> List[Dict[str, Any]]:
    """Parse ordered checklist steps from LLM response."""
    steps = []
    lines = text.split("\n")
    current_step = None

    for line in lines:
        stripped = line.strip()
        num_match = re.match(r"^(\d+)[\.\)]\s+(.*)", stripped)
        if num_match:
            if current_step:
                steps.append(current_step)
            step_num = int(num_match.group(1))
            step_body = num_match.group(2)

            file_match = re.search(r"[`\*]*([a-zA-Z0-9_\-\.\/]+\.[a-zA-Z0-9]+)[`\*]*", step_body)
            file_hint = file_match.group(1) if file_match else ""

            current_step = {
                "step": step_num,
                "text": step_body,
                "file": file_hint
            }
        elif current_step and stripped and not stripped.startswith("#"):
            current_step["text"] += " " + stripped

    if current_step:
        steps.append(current_step)

    if not steps and template_files:
        for i, tf in enumerate(template_files, 1):
            steps.append({
                "step": i,
                "text": f"Create or modify feature module corresponding to template: {tf}",
                "file": tf
            })

    return steps


def _build_guided_change_prompt(
    question: str,
    template_files: List[str],
    connected_links: List[str],
    code_context: str,
    graph_context: str,
    coverage_context: str
) -> str:
    template_str = ", ".join(f"`{f}`" for f in template_files) if template_files else "none found"
    links_str = "\n".join(connected_links) if connected_links else "no explicit link traced"
    return (
        "You are RepoSage, a Principal Software Architect AI specializing in legacy codebase intelligence and guided code changes.\n\n"
        "The developer has asked a task-oriented question about adding, implementing, or creating a feature.\n"
        "Your task is to provide an ordered, numbered checklist of files to create or modify, grounded strictly in an analogous existing feature found in this codebase.\n\n"
        f"Analogous Template Files Identified: {template_str}\n"
        f"Template Component Graph Connections:\n{links_str}\n\n"
        f"Repository Context:\n{graph_context}\n{coverage_context}\n\n"
        f"Retrieved Code Implementations from Template:\n{code_context}\n\n"
        f"Developer Request: {question}\n\n"
        "Strict Instructions:\n"
        "- If no good analogous template feature was found or retrieved code is empty, explicitly state: 'No confident analogous feature template found in currently indexed context; cannot ground guided change steps without inventing unverified structure.' Do NOT invent a plausible-sounding checklist.\n"
        "- Output an ordered, numbered list (e.g. 1. Create/Modify `path/to/file` - purpose and what to model after the template).\n"
        "- For each step, state the exact file path or proposed file path and explain how it mirrors the template pattern.\n"
        "- Do not state absence as fact. Do not invent non-existent APIs or libraries.\n"
        "- Ground every file change in the retrieved code blocks and architecture links above.\n"
        "- Keep the checklist concise and within 1200 words so it can be safely exported to a document.\n\n"
        "Guided Change Checklist:"
    )


async def _resolve_query_plan(repo_path: Optional[str], question: str, refresh: bool = False) -> Dict[str, Any]:
    """Resolve cache hits, retrieval, context, and prompt plan for both streaming and REST Q&A."""
    if not question:
        raise ValueError("Question is required.")

    report = await cache_service.get(f"ingestion_report:{repo_path}") if repo_path else None
    index_id = report.get("indexId") if report else None
    cache_key = _build_cache_key(repo_path, index_id, question)
    semantic_scope = _build_semantic_cache_scope(repo_path, index_id)

    # 1. Exact match cache (Tier 1)
    if not refresh:
        cached = await cache_service.get(cache_key)
        if cached and cached.get("answer"):
            logger.info(f"[Cache] Returning exact in-memory match for: '{question}'")
            return {
                "type": "cache_hit",
                "cache_type": "exact_memory",
                "cached": cached,
                "cache_key": cache_key,
                "semantic_scope": semantic_scope,
            }

        # 2. Semantic vector cache (Tier 2)
        semantic_match = await find_semantic_query_match(semantic_scope, question, threshold=SEMANTIC_CACHE_DIRECT_THRESHOLD)
        if semantic_match and semantic_match.get("matched") and semantic_match.get("answer"):
            logger.info(
                f"[Semantic Cache] ⚡ Returning semantic match ({semantic_match['similarity']*100:.1f}%) "
                f"for '{question}' -> matched: '{semantic_match['matchedQuestion']}'"
            )
            citations = [
                f"{c.get('filePath')}:{c.get('startLine')}-{c.get('endLine')}"
                for c in semantic_match.get("codeCitations", [])
                if isinstance(c, dict) and c.get("filePath")
            ]
            return {
                "type": "semantic_hit",
                "cache_type": "semantic_chromadb",
                "semantic_match": semantic_match,
                "citations": citations,
                "cache_key": cache_key,
                "semantic_scope": semantic_scope,
            }

    # 3. Context & Architecture Graph
    graph_context = ""
    coverage_context = ""
    if repo_path:
        cached_graph = await cache_service.get(f"graph:{repo_path}")
        coverage_context = _build_coverage_context(report)
        if cached_graph and cached_graph.get("links"):
            top_links = "\n".join(f"{l['source']} -> {l['target']}" for l in cached_graph["links"][:10])
            graph_context = f"Known Architecture Connections:\n{top_links}\n\n"

    # 4. Task-Oriented / Guided Change
    if _is_task_oriented_question(question):
        analogous = await find_analogous_feature(repo_path, index_id, question)
        template_files = analogous.get("templateFiles", [])
        code_matches = analogous.get("codeMatches", [])
        diff_matches = analogous.get("diffMatches", [])
        connected_links = analogous.get("connectedLinks", [])
        confidence_level = compute_confidence_level(code_matches)

        code_blocks_str = []
        citations = []
        for i, c in enumerate(code_matches):
            meta = c.get("metadata", {})
            fp = meta.get("filePath", "unknown")
            s = meta.get("startLine", 1)
            e = meta.get("endLine", 1)
            citations.append(f"{fp}:{s}-{e}")
            code_blocks_str.append(f"[Code Block {i+1}] File: {fp} (Lines {s}-{e}):\n```\n{c.get('content')}\n```")

        code_context = _bounded_context("\n\n".join(code_blocks_str))

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

        system_prompt = _build_guided_change_prompt(
            question=question,
            template_files=template_files,
            connected_links=connected_links,
            code_context=code_context,
            graph_context=graph_context,
            coverage_context=coverage_context
        )

        return {
            "type": "guided_steps",
            "is_task_oriented": True,
            "template_files": template_files,
            "system_prompt": system_prompt,
            "confidence_level": confidence_level,
            "code_matches": code_matches,
            "diff_matches": diff_matches,
            "code_meta_list": code_meta_list,
            "git_meta_list": git_meta_list,
            "citations": list(set(citations)),
            "cache_key": cache_key,
            "semantic_scope": semantic_scope,
        }

    # 5. Dual-Vector Code & Diff Retrieval
    file_path_hints = _file_hints(question, report)
    topic_file_hints = _topic_file_hints(question, report)
    file_path_hint = max(file_path_hints, key=len) if file_path_hints else None
    profile_matches = [] if file_path_hints or not (repo_path and index_id) else await find_relevant_files(repo_path, index_id, question)
    profile_hints = [match["filePath"] for match in profile_matches if match.get("filePath")]
    matches = await search_codebase(
        repo_path=repo_path, question=question, top_k=5, index_id=index_id,
        file_path_hint=file_path_hint, file_path_hints=file_path_hints + profile_hints
    )
    focused_matches = _focused_file_matches(
        repo_path,
        file_path_hints + ([] if file_path_hints else topic_file_hints),
    )
    reference_matches = _reference_matches(repo_path, report, question)
    retrieved_matches = focused_matches + reference_matches + matches.get("codeMatches", [])
    seen_matches = set()
    code_matches = []
    for match in retrieved_matches:
        metadata = match.get("metadata", {})
        key = (
            metadata.get("filePath"),
            metadata.get("startLine"),
            metadata.get("endLine"),
        )
        if key not in seen_matches:
            seen_matches.add(key)
            code_matches.append(match)
    diff_matches = matches.get("diffMatches", [])
    confidence_level = compute_confidence_level(code_matches)
    if file_path_hints and not focused_matches:
        confidence_level = "low"

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

    code_context = _bounded_context("\n\n".join(code_blocks_str))
    diff_context = _bounded_context("\n\n".join(diffs_blocks_str), max(4000, MAX_PROMPT_CONTEXT_CHARS // 5))

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

    structural_evidence = any(
        match.get("metadata", {}).get("filePath") in set(([file_path_hint] if file_path_hint else []) + profile_hints)
        and match.get("metadata", {}).get("type") in {"function", "arrow_function", "class"}
        for match in code_matches
    )
    if file_path_hint and _asks_for_signature(question) and not structural_evidence:
        refusal_text = f"I can confirm `{file_path_hint}` exists in the indexed repository, but I do not have its function-level AST content in the current retrieval results. I can't state its actual function signatures from this context."
        return {
            "type": "signature_refusal",
            "refusal_text": refusal_text,
            "confidence_level": "low",
            "code_matches": code_matches,
            "diff_matches": diff_matches,
            "code_meta_list": code_meta_list,
            "git_meta_list": git_meta_list,
            "citations": list(set(citations)),
            "cache_key": cache_key,
            "semantic_scope": semantic_scope,
        }

    # Strict Grounding Prompt Template (PDF Pages 110 & 114)
    system_prompt = (
        "You are RepoSage, a Principal Software Architect AI specializing in legacy codebase intelligence and architectural decision tracing.\n\n"
        "Your goal is to answer the developer's question accurately, citing specific files, functions, line numbers, and historical git reasons.\n\n"
        f"Repository Context:\n{graph_context}\n{coverage_context}\n\n"
        f"Retrieved Code Implementations:\n{code_context}\n\n"
        + (f"Retrieved Historical Git Changes (Why it was built this way):\n{diff_context}\n\n" if diff_context else "")
        + f"Developer Question: {question}\n\n"
        "Instructions:\n"
        "- Answer only the developer's question. Keep the answer short and easy to understand; do not add unrelated features, code, or architecture discussion.\n"
        "- Separate facts directly shown in retrieved code from reasonable inferences. Never present an inference as a confirmed fact.\n"
        "- Explain the architectural reason and technical flow only when it directly answers the question.\n"
        "- Prefer directly retrieved implementation files and runtime settings over README descriptions or stale configuration files.\n"
        "- Treat a configuration file as active only when retrieved code loads it or a runtime settings object exposes the same value; otherwise label it stale or unverified.\n"
        "- For usage/dead-code questions, distinguish a declaration from references and report the exact reference locations found.\n"
        "- Reference exact file names and line ranges when discussing code.\n"
        "- Absence from retrieved snippets is NOT evidence that a component does not exist. Never state that a module/file/component is absent as a fact unless the indexed file inventory directly proves it was excluded and you explain that limitation. If evidence is incomplete, say exactly: 'I found no direct evidence in the currently indexed context; this does not prove the component is absent.'\n"
        "- When the inventory lists a relevant module but snippets were not retrieved, acknowledge the module exists in the index and avoid inventing its implementation details.\n"
        "- Do not state a function name, parameter name, or signature unless the exact declaration is present verbatim in Retrieved Code Implementations. If structural code for a named file is unavailable, state that you cannot confirm its actual signature.\n"
        f"- Semantic file-routing candidates for this question: {', '.join(profile_hints) or 'none'}. These candidates only guide retrieval; cite retrieved code, not the candidate list.\n"
        "- If historical diffs provide context on WHY a decision or change was made, highlight it under a '🏛️ Architectural Decision History' section.\n"
        "- Use clean Markdown format with code snippets where helpful.\n\n"
        "- Keep the answer focused and within 1200 words so it remains suitable for PDF export.\n\n"
        "Answer:"
    )

    return {
        "type": "chat",
        "is_task_oriented": False,
        "system_prompt": system_prompt,
        "confidence_level": confidence_level,
        "code_matches": code_matches,
        "diff_matches": diff_matches,
        "code_meta_list": code_meta_list,
        "git_meta_list": git_meta_list,
        "citations": list(set(citations)),
        "cache_key": cache_key,
        "semantic_scope": semantic_scope,
    }


async def query_codebase(repo_path: Optional[str], question: str, refresh: bool = False) -> Dict[str, Any]:
    plan = await _resolve_query_plan(repo_path, question, refresh=refresh)
    plan_type = plan["type"]

    if plan_type == "cache_hit":
        cached = plan["cached"]
        return {
            **cached,
            "fromCache": True,
            "cacheType": "exact_memory",
            "confidenceLevel": cached.get("confidenceLevel", "high")
        }

    if plan_type == "semantic_hit":
        sm = plan["semantic_match"]
        return {
            "answer": sm["answer"],
            "question": question,
            "matchedQuestion": sm["matchedQuestion"],
            "similarity": sm["similarity"],
            "confidenceLevel": sm.get("confidenceLevel", "high"),
            "fromCache": True,
            "semanticCache": True,
            "cacheType": "semantic_chromadb",
            "codeMatches": sm.get("codeCitations", []),
            "diffMatches": sm.get("gitCitations", []),
            "citations": plan["citations"]
        }

    if plan_type == "signature_refusal":
        return {
            "answer": plan["refusal_text"],
            "question": question,
            "codeMatches": plan["code_matches"],
            "diffMatches": plan["diff_matches"],
            "signatureEvidenceMissing": True,
            "confidenceLevel": "low",
            "citations": plan["citations"]
        }

    is_task_oriented = plan.get("is_task_oriented", False)
    semantic_scope = plan["semantic_scope"]
    cache_key = plan["cache_key"]
    code_matches = plan["code_matches"]
    diff_matches = plan["diff_matches"]
    code_meta_list = plan["code_meta_list"]
    git_meta_list = plan["git_meta_list"]
    citations = plan["citations"]
    confidence_level = plan["confidence_level"]
    template_files = plan.get("template_files", [])

    try:
        chat_model = get_chat_model(temperature=0.2)
        response = await chat_model.ainvoke(plan["system_prompt"])
        if isinstance(response.content, str):
            answer_text = response.content
        elif isinstance(response.content, list):
            answer_text = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in response.content)
        else:
            answer_text = str(response.content)
    except Exception as llm_error:
        logger.warning(f"[LLM] Cloud LLM unavailable ({llm_error}). Checking offline semantic fallback...")
        fallback_match = await find_semantic_query_match(semantic_scope, question, threshold=SEMANTIC_CACHE_OFFLINE_THRESHOLD)
        if fallback_match and fallback_match.get("matched") and fallback_match.get("answer"):
            if is_task_oriented:
                return {
                    "type": "guided_steps",
                    "steps": fallback_match.get("steps", []),
                    "basedOn": fallback_match.get("basedOn", template_files),
                    "answer": fallback_match["answer"],
                    "question": question,
                    "confidenceLevel": fallback_match.get("confidenceLevel", "medium"),
                    "fromCache": True,
                    "semanticCache": True,
                    "offlineFallback": True,
                    "cacheType": "offline_semantic_fallback",
                    "codeMatches": code_matches,
                    "diffMatches": diff_matches,
                    "citations": citations
                }
            return {
                "answer": (
                    f"> ⚡ **[Offline Mode Active]** Network connection to cloud LLM is offline. "
                    f"Showing nearest semantic match ({fallback_match['similarity']*100:.1f}% match to: *\"{fallback_match['matchedQuestion']}\"*):\n\n"
                    + fallback_match["answer"]
                ),
                "question": question,
                "matchedQuestion": fallback_match["matchedQuestion"],
                "similarity": fallback_match["similarity"],
                "confidenceLevel": fallback_match.get("confidenceLevel", "medium"),
                "fromCache": True,
                "semanticCache": True,
                "offlineFallback": True,
                "cacheType": "offline_semantic_fallback",
                "codeMatches": code_matches,
                "diffMatches": diff_matches,
                "citations": citations
            }

        no_confident_msg = (
            "## No confident answer available\n\nRepoSage could not reach the live LLM, and no cached answer met the 80% similarity safety threshold for this question."
            if is_task_oriented else
            "## No confident answer available\n\nRepoSage could not reach the live LLM, and no cached answer met the 80% similarity safety threshold for this question. It will not show a loosely related answer as if it were yours. Please retry when the LLM is available."
        )
        res = {
            "answer": no_confident_msg,
            "question": question,
            "fromCache": False,
            "offlineNoConfidentAnswer": True,
            "confidenceLevel": "low",
            "cacheType": "offline_no_confident_match",
            "codeMatches": code_matches,
            "diffMatches": diff_matches,
            "citations": citations
        }
        if is_task_oriented:
            res["type"] = "guided_steps"
            res["steps"] = []
            res["basedOn"] = template_files
        return res

    result: Dict[str, Any] = {
        "answer": answer_text,
        "question": question,
        "confidenceLevel": confidence_level,
        "codeMatches": code_matches,
        "diffMatches": diff_matches,
        "codeCitations": code_meta_list,
        "gitCitations": git_meta_list,
        "citations": citations
    }
    if is_task_oriented:
        result["type"] = "guided_steps"
        result["steps"] = _parse_guided_steps(answer_text, template_files)
        result["basedOn"] = template_files

    await cache_service.set(cache_key, result, 86400)
    await store_query_cache(
        repo_path=semantic_scope,
        question=question,
        answer=answer_text,
        code_citations=code_meta_list,
        git_citations=git_meta_list
    )
    return result


async def stream_query_codebase(
    repo_path: Optional[str],
    question: str,
    refresh: bool = False
) -> AsyncGenerator[Dict[str, Any], None]:
    """Stream answer generation token-by-token using SSE while preserving caching and calibration."""
    plan = await _resolve_query_plan(repo_path, question, refresh=refresh)
    plan_type = plan["type"]

    if plan_type == "cache_hit":
        cached = plan["cached"]
        logger.info(f"[Cache] Returning exact in-memory match for streaming: '{question}'")
        yield {
            "type": "meta",
            "responseType": cached.get("type", "chat"),
            "fromCache": True,
            "cacheType": "exact_memory",
            "confidenceLevel": cached.get("confidenceLevel", "high"),
            "basedOn": cached.get("basedOn", []),
            "steps": cached.get("steps", []),
            "codeCitations": cached.get("codeCitations", []),
            "gitCitations": cached.get("gitCitations", []),
            "citations": cached.get("citations", []),
            "matchedQuestion": cached.get("matchedQuestion")
        }
        yield {"type": "token", "token": cached["answer"]}
        yield {
            "type": "done",
            **cached,
            "fromCache": True,
            "cacheType": "exact_memory",
            "confidenceLevel": cached.get("confidenceLevel", "high")
        }
        return

    if plan_type == "semantic_hit":
        sm = plan["semantic_match"]
        citations = plan["citations"]
        yield {
            "type": "meta",
            "fromCache": True,
            "semanticCache": True,
            "cacheType": "semantic_chromadb",
            "confidenceLevel": sm.get("confidenceLevel", "high"),
            "similarity": sm.get("similarity"),
            "matchedQuestion": sm.get("matchedQuestion"),
            "codeCitations": sm.get("codeCitations", []),
            "gitCitations": sm.get("gitCitations", []),
            "citations": citations
        }
        yield {"type": "token", "token": sm["answer"]}
        yield {
            "type": "done",
            "answer": sm["answer"],
            "question": question,
            "matchedQuestion": sm["matchedQuestion"],
            "similarity": sm["similarity"],
            "confidenceLevel": sm.get("confidenceLevel", "high"),
            "fromCache": True,
            "semanticCache": True,
            "cacheType": "semantic_chromadb",
            "codeCitations": sm.get("codeCitations", []),
            "gitCitations": sm.get("gitCitations", []),
            "citations": citations
        }
        return

    if plan_type == "signature_refusal":
        refusal_text = plan["refusal_text"]
        yield {
            "type": "meta",
            "signatureEvidenceMissing": True,
            "confidenceLevel": "low",
            "codeCitations": plan["code_meta_list"],
            "gitCitations": plan["git_meta_list"],
            "citations": plan["citations"]
        }
        yield {"type": "token", "token": refusal_text}
        yield {
            "type": "done",
            "answer": refusal_text,
            "question": question,
            "codeMatches": plan["code_matches"],
            "diffMatches": plan["diff_matches"],
            "signatureEvidenceMissing": True,
            "confidenceLevel": "low",
            "citations": plan["citations"]
        }
        return

    is_task_oriented = plan.get("is_task_oriented", False)
    semantic_scope = plan["semantic_scope"]
    cache_key = plan["cache_key"]
    code_matches = plan["code_matches"]
    diff_matches = plan["diff_matches"]
    code_meta_list = plan["code_meta_list"]
    git_meta_list = plan["git_meta_list"]
    citations = plan["citations"]
    confidence_level = plan["confidence_level"]
    template_files = plan.get("template_files", [])

    meta_event = {
        "type": "meta",
        "confidenceLevel": confidence_level,
        "codeCitations": code_meta_list,
        "gitCitations": git_meta_list,
        "citations": citations
    }
    if is_task_oriented:
        meta_event["responseType"] = "guided_steps"
        meta_event["basedOn"] = template_files
    yield meta_event

    full_chunks = []
    try:
        chat_model = get_chat_model(temperature=0.2)
        async for chunk in chat_model.astream(plan["system_prompt"]):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            if isinstance(content, list):
                text_chunk = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
            else:
                text_chunk = str(content)
            if text_chunk:
                full_chunks.append(text_chunk)
                yield {"type": "token", "token": text_chunk}
        answer_text = "".join(full_chunks)
    except Exception as llm_error:
        logger.warning(f"[LLM] Stream error ({llm_error}). Checking offline semantic fallback...")
        fallback_match = await find_semantic_query_match(semantic_scope, question, threshold=SEMANTIC_CACHE_OFFLINE_THRESHOLD)
        if fallback_match and fallback_match.get("matched") and fallback_match.get("answer"):
            if is_task_oriented:
                yield {"type": "token", "token": fallback_match["answer"]}
                yield {
                    "type": "done",
                    "responseType": "guided_steps",
                    "steps": fallback_match.get("steps", []),
                    "basedOn": fallback_match.get("basedOn", template_files),
                    "answer": fallback_match["answer"],
                    "question": question,
                    "confidenceLevel": fallback_match.get("confidenceLevel", "medium"),
                    "fromCache": True,
                    "semanticCache": True,
                    "offlineFallback": True,
                    "cacheType": "offline_semantic_fallback",
                    "citations": citations
                }
                return
            fallback_answer = (
                f"> ⚡ **[Offline Mode Active]** Network connection to cloud LLM is offline. "
                f"Showing nearest semantic match ({fallback_match['similarity']*100:.1f}% match to: *\"{fallback_match['matchedQuestion']}\"*):\n\n"
                + fallback_match["answer"]
            )
            yield {"type": "token", "token": fallback_answer}
            yield {
                "type": "done",
                "answer": fallback_answer,
                "question": question,
                "matchedQuestion": fallback_match["matchedQuestion"],
                "similarity": fallback_match["similarity"],
                "confidenceLevel": fallback_match.get("confidenceLevel", "medium"),
                "fromCache": True,
                "semanticCache": True,
                "offlineFallback": True,
                "cacheType": "offline_semantic_fallback",
                "citations": citations
            }
            return

        no_ans = (
            "## No confident answer available\n\nRepoSage could not reach the live LLM, and no cached answer met the 80% similarity safety threshold for this question."
            if is_task_oriented else
            "## No confident answer available\n\nRepoSage could not reach the live LLM, and no cached answer met the 80% similarity safety threshold for this question. It will not show a loosely related answer as if it were yours. Please retry when the LLM is available."
        )
        yield {"type": "token", "token": no_ans}
        done_event = {
            "type": "done",
            "answer": no_ans,
            "question": question,
            "fromCache": False,
            "offlineNoConfidentAnswer": True,
            "confidenceLevel": "low",
            "cacheType": "offline_no_confident_match",
            "citations": citations
        }
        if is_task_oriented:
            done_event["responseType"] = "guided_steps"
            done_event["steps"] = []
            done_event["basedOn"] = template_files
        yield done_event
        return

    result = {
        "answer": answer_text,
        "question": question,
        "confidenceLevel": confidence_level,
        "codeMatches": code_matches,
        "diffMatches": diff_matches,
        "codeCitations": code_meta_list,
        "gitCitations": git_meta_list,
        "citations": citations
    }
    if is_task_oriented:
        result["type"] = "guided_steps"
        result["steps"] = _parse_guided_steps(answer_text, template_files)
        result["basedOn"] = template_files

    await cache_service.set(cache_key, result, 86400)
    await store_query_cache(
        repo_path=semantic_scope,
        question=question,
        answer=answer_text,
        code_citations=code_meta_list,
        git_citations=git_meta_list
    )

    yield {"type": "done", **result}
