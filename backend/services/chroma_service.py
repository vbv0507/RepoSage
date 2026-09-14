import os
import math
import time
import json
import hashlib
import logging
import asyncio
import threading
import requests
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
import chromadb.utils.embedding_functions as chromadb_ef

import socket

logger = logging.getLogger("chroma_service")

CHROMA_URL = os.getenv("CHROMA_URL", "").strip()

class ResilientEmbeddingFunction(EmbeddingFunction):
    """
    Resilient multi-tier embedding function:
    1. Google Gemini Embeddings (models/gemini-embedding-001 with 384 dim, fallback to models/text-embedding-004)
    2. Local ONNX DefaultEmbeddingFunction (all-MiniLM-L6-v2, 384 dim) with concurrency guard
    3. Deterministic normalized hash vector emergency fallback (384 dim, zero crashes)
    """
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        self.preferred_model = None
        self._onnx_lock = threading.Lock()

    def __call__(self, input: Documents) -> Embeddings:
        # 1. Try Gemini Cloud Embeddings with 384 dimensions
        if self.api_key:
            candidate_models = [self.preferred_model] if self.preferred_model else ["models/gemini-embedding-001", "models/text-embedding-004"]
            for model_name in candidate_models:
                if not model_name:
                    continue
                requests_data = [
                    {
                        "model": model_name,
                        "content": {"parts": [{"text": (text or "")[:2048]}]},
                        "outputDimensionality": 384
                    }
                    for text in input
                ]
                url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:batchEmbedContents?key={self.api_key}"
                for attempt in range(2):
                    resp = None
                    try:
                        resp = requests.post(url, json={"requests": requests_data}, timeout=(5, 12))
                        if resp.status_code == 200:
                            data = resp.json()
                            if "embeddings" in data and len(data["embeddings"]) > 0:
                                self.preferred_model = model_name
                                return [e["values"] for e in data["embeddings"]]
                        elif resp.status_code == 404:
                            break  # Try next candidate model
                        else:
                            logger.warning(f"[ChromaDB] Gemini {model_name} attempt {attempt + 1} returned status {resp.status_code}")
                    except Exception as e:
                        logger.warning(f"[ChromaDB] Gemini {model_name} attempt {attempt + 1} failed: {e}")
                    
                    if attempt == 0:
                        wait_time = 1.2 if (resp is not None and resp.status_code == 429) else 0.3
                        time.sleep(wait_time)

        # 2. Resilient Local ONNX Embedding Fallback (all-MiniLM-L6-v2) - Thread-locked to avoid CPU/OOM spikes
        try:
            with self._onnx_lock:
                logger.warning("[ChromaDB] Gemini embedding unavailable. Falling back to local ONNX embeddings (all-MiniLM-L6-v2).")
                local_ef = get_local_query_embedding_function()
                if local_ef is not None and not isinstance(local_ef, ResilientEmbeddingFunction):
                    return local_ef(input)
        except Exception as onnx_err:
            logger.warning(f"[ChromaDB] Local ONNX fallback failed: {onnx_err}. Using emergency hash vectors.")

        # 3. Emergency Normalized Hash Vector (384 dimensions matching collection dimension)
        results = []
        for text in input:
            vec = [0.0] * 384
            s = text or ""
            for i, ch in enumerate(s):
                vec[i % 384] += ord(ch) * 0.001
            mag = math.sqrt(sum(v * v for v in vec)) or 1.0
            results.append([v / mag for v in vec])
        return results


_client = None
_embedding_fn = None
_code_collection = None
_diffs_collection = None
_queries_collection = None
_file_profiles_collection = None
_local_embedding_fn = None
_local_ef_lock = threading.Lock()
_ef_lock = threading.Lock()

def get_local_query_embedding_function():
    global _local_embedding_fn
    if _local_embedding_fn is None:
        with _local_ef_lock:
            if _local_embedding_fn is None:
                try:
                    _local_embedding_fn = chromadb_ef.DefaultEmbeddingFunction()
                except Exception as e:
                    logger.warning(f"[ChromaDB] DefaultEmbeddingFunction unavailable: {e}. Using resilient embedding.")
                    _local_embedding_fn = get_embedding_function()
    return _local_embedding_fn

def get_embedding_function() -> ResilientEmbeddingFunction:
    global _embedding_fn
    if _embedding_fn is None:
        with _ef_lock:
            if _embedding_fn is None:
                _embedding_fn = ResilientEmbeddingFunction()
    return _embedding_fn

def get_chroma_client():
    global _client
    if _client is not None:
        return _client

    # Try connecting to remote/local HTTP server only if CHROMA_URL is explicitly configured
    if CHROMA_URL and CHROMA_URL.lower() not in ("none", "false", "local", "disabled") and CHROMA_URL.startswith("http"):
        try:
            parts = CHROMA_URL.replace("http://", "").replace("https://", "").split(":")
            host = parts[0]
            port = int(parts[1]) if len(parts) > 1 else 8000
            # Fast TCP socket check with 2s timeout to prevent 30-60s OS TCP connection hang
            with socket.create_connection((host, port), timeout=2.0):
                pass
            client = chromadb.HttpClient(host=host, port=port)
            client.heartbeat()
            _client = client
            return _client
        except Exception as e:
            logger.info(f"[ChromaDB] HTTP ChromaDB not reachable at {CHROMA_URL}: {e}. Initializing persistent local DB.")

    # Fallback to local persistent storage immediately
    persist_dir = os.path.abspath("./chroma_data")
    os.makedirs(persist_dir, exist_ok=True)
    _client = chromadb.PersistentClient(path=persist_dir)
    return _client

def check_chroma_connection() -> dict:
    try:
        c = get_chroma_client()
        hb = c.heartbeat()
        return {"connected": True, "heartbeat": hb, "embeddingType": "Gemini-001 + Resilient Hash + Local ONNX"}
    except Exception as e:
        return {"connected": False, "error": str(e)}

def _get_or_init_collection(name: str, embedding_fn=None):
    c = get_chroma_client()
    ef = embedding_fn or get_embedding_function()
    try:
        return c.get_or_create_collection(
            name=name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"}
        )
    except Exception as e:
        if "dimension" in str(e).lower():
            logger.info(f"[ChromaDB] Resetting collection {name} for dimension match...")
            try:
                c.delete_collection(name=name)
            except Exception:
                pass
            return c.create_collection(
                name=name,
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"}
            )
        raise e

def get_code_collection():
    global _code_collection
    if _code_collection is None:
        _code_collection = _get_or_init_collection("reposage_code")
    return _code_collection

def get_diffs_collection():
    global _diffs_collection
    if _diffs_collection is None:
        _diffs_collection = _get_or_init_collection("reposage_diffs")
    return _diffs_collection

def get_queries_collection():
    global _queries_collection
    if _queries_collection is None:
        _queries_collection = _get_or_init_collection("reposage_queries", embedding_fn=get_embedding_function())
    return _queries_collection


def get_file_profiles_collection():
    global _file_profiles_collection
    if _file_profiles_collection is None:
        _file_profiles_collection = _get_or_init_collection("reposage_file_profiles")
    return _file_profiles_collection


async def delete_repo_file_vectors(repo_path: str, file_paths: Any) -> dict:
    """Delete code vectors and file profiles for specific files in a repo (incremental delete)."""
    if isinstance(file_paths, str):
        file_paths = [file_paths]
    if not file_paths:
        return {"deleted": 0}
    code_coll = get_code_collection()
    profile_coll = get_file_profiles_collection()
    deleted_count = 0
    for fp in file_paths:
        try:
            code_coll.delete(where={"$and": [{"repoPath": repo_path}, {"filePath": fp}]})
            deleted_count += 1
        except Exception as exc:
            logger.warning(f"Could not delete code chunks for {repo_path} ({fp}): {exc}")
        try:
            profile_coll.delete(where={"$and": [{"repoPath": repo_path}, {"filePath": fp}]})
        except Exception as exc:
            logger.warning(f"Could not delete profile for {repo_path} ({fp}): {exc}")
    return {"deleted": deleted_count}


async def store_file_profiles(repo_path: str, parsed_files: List[Dict[str, Any]], index_id: str, clear_prior: bool = False) -> dict:
    """Embed one compact role/symbol profile per source file for routing."""
    coll = get_file_profiles_collection()
    if clear_prior:
        try:
            coll.delete(where={"repoPath": repo_path})
        except Exception as exc:
            logger.warning("Could not clear old file profiles for %s: %s", repo_path, exc)
    ids, documents, metadatas = [], [], []
    for parsed in parsed_files:
        file_path = parsed["filePath"]
        symbols = []
        for chunk in parsed.get("chunks", [])[:30]:
            if chunk.get("type") in {"function", "arrow_function", "class"}:
                symbols.append(f"{chunk.get('type')} {chunk.get('name')}: {chunk.get('summary', '')}\n{chunk.get('code', '')[:500]}")
        profile = f"File: {file_path}\nExtension: {parsed.get('extension')}\n" + "\n".join(symbols)
        if not symbols:
            profile += "\nContent summary:\n" + "\n".join(chunk.get("code", "")[:300] for chunk in parsed.get("chunks", [])[:3])
        ids.append("profile_" + hashlib.sha256(f"{repo_path}:{file_path}".encode()).hexdigest()[:32])
        documents.append(profile[:12000])
        metadatas.append({"repoPath": repo_path, "indexId": index_id, "filePath": file_path})
    stored_count = 0
    for offset in range(0, len(ids), 50):
        try:
            coll.add(
                ids=ids[offset:offset + 50],
                documents=documents[offset:offset + 50],
                metadatas=metadatas[offset:offset + 50],
            )
            stored_count += len(ids[offset:offset + 50])
        except Exception as exc:
            logger.warning("Could not store file-profile batch: %s", exc)
    return {"storedCount": stored_count}


async def find_relevant_files(repo_path: str, index_id: Optional[str] = None, question: str = "", top_k: int = 3) -> List[Dict[str, Any]]:
    try:
        res = get_file_profiles_collection().query(query_texts=[question], n_results=top_k, where=_where(repo_path))
        if not res or not res.get("metadatas") or not res["metadatas"][0]:
            return []
        distances = res.get("distances", [[]])[0]
        return [{"filePath": meta.get("filePath"), "similarity": round(max(0.0, 1.0 - float(distances[i])), 4) if i < len(distances) else None} for i, meta in enumerate(res["metadatas"][0]) if meta.get("filePath")]
    except Exception as exc:
        logger.warning("File-profile routing failed: %s", exc)
        return []

async def store_code_chunks(repo_path: str, chunks: List[Dict[str, Any]], index_id: str, clear_prior: bool = False, on_progress: Optional[Any] = None) -> dict:
    if not chunks:
        return {"storedCount": 0, "failedFiles": []}
    coll = get_code_collection()
    
    # Delete prior vectors for this repo only if explicitly requested (e.g. force refresh)
    if clear_prior:
        try:
            coll.delete(where={"repoPath": repo_path})
        except Exception:
            pass

    ids = []
    documents = []
    metadatas = []
    seen_ids = set()

    for chunk in chunks:
        file_path = chunk.get("filePath", "")
        start_line = chunk.get("startLine", 1)
        name = chunk.get("name") or "unnamed"
        code = chunk.get("code") or ""
        uid = "code_" + hashlib.sha256(f"{repo_path}:{file_path}:{start_line}:{name}:{code[:80]}".encode()).hexdigest()[:32]
        if uid in seen_ids:
            continue
        seen_ids.add(uid)

        ids.append(uid)
        documents.append(code[:2000])
        metadatas.append({
            "repoPath": repo_path,
            "indexId": index_id,
            "filePath": file_path,
            "name": name,
            "type": chunk.get("type") or "code",
            "startLine": int(start_line),
            "endLine": int(chunk.get("endLine", 1)),
            "summary": (chunk.get("summary") or "")[:400]
        })

    # Sequential batch add to prevent memory & CPU spikes in container environments
    BATCH_SIZE = 50
    failed_files = []
    batches = []
    for i in range(0, len(ids), BATCH_SIZE):
        batches.append((
            ids[i:i + BATCH_SIZE],
            documents[i:i + BATCH_SIZE],
            metadatas[i:i + BATCH_SIZE]
        ))

    async def _add_batch(b_ids, b_docs, b_metas):
        try:
            await asyncio.to_thread(coll.add, ids=b_ids, documents=b_docs, metadatas=b_metas)
            return len(b_ids), None
        except Exception as exc:
            affected_files = sorted({meta["filePath"] for meta in b_metas})
            logger.error("Failed to embed code batch for %s: %s", affected_files, exc)
            batch_fails = [{"path": fp, "reason": f"embedding_error: {exc}"} for fp in affected_files]
            return 0, batch_fails

    stored_count = 0
    for idx, b in enumerate(batches):
        count, fails = await _add_batch(b[0], b[1], b[2])
        stored_count += count
        if fails:
            failed_files.extend(fails)
        if on_progress:
            processed = min((idx + 1) * BATCH_SIZE, len(ids))
            on_progress({
                "step": "embedding_progress",
                "current": processed,
                "total": len(ids),
                "message": f"Indexed {processed}/{len(ids)} code chunks into vector database..."
            })
        await asyncio.sleep(0.01)

    return {"storedCount": stored_count, "failedFiles": failed_files}

async def store_diff_summaries(repo_path: str, diffs: List[Dict[str, Any]], index_id: str) -> dict:
    if not diffs:
        return {"storedCount": 0}
    coll = get_diffs_collection()

    try:
        coll.delete(where={"repoPath": repo_path})
    except Exception:
        pass

    ids = []
    documents = []
    metadatas = []

    for i, diff in enumerate(diffs):
        h = diff.get("hash", f"h_{i}")
        ids.append(f"diff_{h[:8]}_{i}")
        intent = diff.get("intentSummary") or ""
        snippet = diff.get("diffSnippet") or ""
        documents.append(f"{intent}\n\nDiff details:\n{snippet}")
        metadatas.append({
            "repoPath": repo_path,
            "indexId": index_id,
            "hash": h,
            "author": diff.get("author") or "Unknown",
            "date": diff.get("date") or "",
            "rawMessage": diff.get("rawMessage") or "",
            "isSynthesized": "true" if diff.get("isSynthesized") else "false"
        })

    BATCH_SIZE = 20
    for i in range(0, len(ids), BATCH_SIZE):
        coll.add(
            ids=ids[i:i + BATCH_SIZE],
            documents=documents[i:i + BATCH_SIZE],
            metadatas=metadatas[i:i + BATCH_SIZE]
        )

    return {"storedCount": len(diffs)}

def _where(repo_path: Optional[str], index_id: Optional[str] = None, file_path: Optional[str] = None) -> Optional[dict]:
    clauses = []
    if repo_path:
        clauses.append({"repoPath": repo_path})
    if file_path:
        clauses.append({"filePath": file_path})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _matches_from_result(result: Optional[dict]) -> List[dict]:
    matches = []
    if not result or not result.get("documents") or not result["documents"][0]:
        return matches
    docs = result["documents"][0]
    metas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    for index, document in enumerate(docs):
        matches.append({"type": "code", "content": document, "metadata": metas[index] if index < len(metas) else {}, "distance": distances[index] if index < len(distances) else None})
    return matches


async def search_codebase(repo_path: Optional[str], question: str, top_k: int = 6, index_id: Optional[str] = None, file_path_hint: Optional[str] = None, file_path_hints: Optional[List[str]] = None) -> dict:
    code_coll = get_code_collection()
    diffs_coll = get_diffs_collection()

    where_filter = _where(repo_path)

    # 1. Query Code
    try:
        code_res = await asyncio.to_thread(code_coll.query, query_texts=[question], n_results=top_k, where=where_filter)
    except Exception:
        code_res = None

    # An unscoped retry is only safe for callers that intentionally did not
    # specify a repository/index.  Otherwise it could surface another
    # repository or a stale indexing run.
    if not repo_path and (not code_res or not code_res.get("documents") or not code_res["documents"][0]):
        try:
            code_res = await asyncio.to_thread(code_coll.query, query_texts=[question], n_results=top_k)
        except Exception:
            code_res = None

    # 2. Query Historical Diffs
    try:
        diffs_res = await asyncio.to_thread(diffs_coll.query, query_texts=[question], n_results=3, where=where_filter)
    except Exception:
        diffs_res = None

    if not repo_path and (not diffs_res or not diffs_res.get("documents") or not diffs_res["documents"][0]):
        try:
            diffs_res = await asyncio.to_thread(diffs_coll.query, query_texts=[question], n_results=3)
        except Exception:
            diffs_res = None

    code_matches = _matches_from_result(code_res)
    # A file-specific question needs that file's structural chunks before
    # generic semantic matches. Merge it first and deduplicate by line range.
    focused_paths = list(dict.fromkeys(([file_path_hint] if file_path_hint else []) + (file_path_hints or [])))
    if focused_paths:
        try:
            focused = []
            for focused_path in focused_paths[:3]:
                f_res = await asyncio.to_thread(code_coll.query, query_texts=[question], n_results=8, where=_where(repo_path, file_path=focused_path))
                focused.extend(_matches_from_result(f_res))
            seen = set()
            code_matches = [match for match in focused + code_matches if not ((key := (match["metadata"].get("filePath"), match["metadata"].get("startLine"))) in seen or seen.add(key))]
        except Exception as exc:
            logger.warning("Focused retrieval failed for %s: %s", focused_paths, exc)

    diff_matches = []
    if diffs_res and diffs_res.get("documents") and diffs_res["documents"][0]:
        docs = diffs_res["documents"][0]
        metas = diffs_res["metadatas"][0] if diffs_res.get("metadatas") else [{}] * len(docs)
        distances = diffs_res["distances"][0] if diffs_res.get("distances") else [None] * len(docs)
        for i, doc in enumerate(docs):
            diff_matches.append({
                "type": "git_archaeology",
                "content": doc,
                "metadata": metas[i] if i < len(metas) else {},
                "distance": distances[i] if i < len(distances) else None
            })

    return {
        "codeMatches": code_matches,
        "diffMatches": diff_matches
    }

async def get_repo_vector_stats(repo_path: str, index_id: Optional[str] = None) -> dict:
    try:
        coll = get_code_collection()
        PAGE_SIZE = 5000
        offset = 0
        all_ids = []
        file_paths = set()
        is_truncated = False

        while True:
            try:
                res = coll.get(where=_where(repo_path), limit=PAGE_SIZE, offset=offset, include=["metadatas"])
            except Exception as get_err:
                logger.warning(f"Error fetching vector stats page at offset {offset}: {get_err}")
                is_truncated = True
                break

            if not res or not res.get("ids"):
                break
            
            ids = res["ids"]
            all_ids.extend(ids)
            for meta in (res.get("metadatas") or []):
                if meta and meta.get("filePath"):
                    file_paths.add(meta["filePath"])
            
            if len(ids) < PAGE_SIZE:
                break
            offset += len(ids)
            
            # Guard against runaway pagination
            if offset >= 200000:
                is_truncated = True
                break

        return {
            "exists": len(all_ids) > 0,
            "count": len(all_ids),
            "filesCount": len(file_paths),
            "truncated": is_truncated
        }
    except Exception as e:
        logger.warning(f"Error getting repo vector stats: {e}")
        return {"exists": False, "count": 0, "filesCount": 0, "truncated": False}


async def clear_repo_vectors(repo_path: str) -> dict:
    try:
        code_coll = get_code_collection()
        diffs_coll = get_diffs_collection()
        queries_coll = get_queries_collection()
        code_coll.delete(where={"repoPath": repo_path})
        diffs_coll.delete(where={"repoPath": repo_path})
        try:
            queries_coll.delete(where={"repoPath": repo_path})
        except Exception:
            pass
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def store_query_cache(
    repo_path: Optional[str],
    question: str,
    answer: str,
    code_citations: Optional[List[Any]] = None,
    git_citations: Optional[List[Any]] = None
) -> dict:
    """
    Store an answered question into the semantic vector cache using local ONNX embeddings.
    """
    if not question or not answer:
        return {"stored": False}
    try:
        coll = get_queries_collection()
        clean_q = question.strip()
        uid = f"sq_{abs(hash(f'{repo_path}:{clean_q.lower()}')) % 100000000}_{int(time.time())}"
        
        # Serialize citations for retrieval
        code_c_json = json.dumps(code_citations or [])[:3000]
        git_c_json = json.dumps(git_citations or [])[:3000]
        
        coll.add(
            ids=[uid],
            documents=[clean_q],
            metadatas=[{
                "repoPath": repo_path or "global",
                "question": clean_q,
                "answer": answer[:8000],
                "codeCitations": code_c_json,
                "gitCitations": git_c_json,
                "timestamp": int(time.time())
            }]
        )
        logger.info(f"[Semantic Cache] 💾 Cached query embedding for: '{clean_q}'")
        return {"stored": True, "id": uid}
    except Exception as e:
        logger.warning(f"[Semantic Cache] Store error: {e}")
        return {"stored": False, "error": str(e)}

async def find_semantic_query_match(
    repo_path: Optional[str],
    question: str,
    threshold: float = 0.85
) -> Optional[Dict[str, Any]]:
    """
    Find a semantically similar cached question using local ONNX embeddings.
    Cosine similarity = 1 - distance. If sim >= threshold (e.g. 0.85), returns cached answer.
    """
    if not question or not question.strip():
        return None
    try:
        coll = get_queries_collection()
        where_filter = {"repoPath": repo_path} if repo_path else None
        
        res = coll.query(
            query_texts=[question.strip()],
            n_results=1,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )
        
        # Only check without where filter if repo_path was intentionally not specified
        if not repo_path and (not res or not res.get("documents") or not res["documents"][0]):
            try:
                res = coll.query(
                    query_texts=[question.strip()],
                    n_results=1,
                    include=["documents", "metadatas", "distances"]
                )
            except Exception:
                res = None

        if res and res.get("documents") and res["documents"][0] and len(res["documents"][0]) > 0:
            dist = res["distances"][0][0]
            sim = max(0.0, 1.0 - dist)
            meta = res["metadatas"][0][0] if res.get("metadatas") and res["metadatas"][0] else {}
            doc_text = res["documents"][0][0]
            
            code_citations = []
            git_citations = []
            try:
                if meta.get("codeCitations"):
                    code_citations = json.loads(meta["codeCitations"])
                if meta.get("gitCitations"):
                    git_citations = json.loads(meta["gitCitations"])
            except Exception:
                pass

            matched_obj = {
                "matched": sim >= threshold,
                "similarity": round(float(sim), 4),
                "distance": round(float(dist), 4),
                "matchedQuestion": meta.get("question", doc_text),
                "answer": meta.get("answer", ""),
                "codeCitations": code_citations,
                "gitCitations": git_citations,
                "timestamp": meta.get("timestamp", 0)
            }

            if matched_obj["matched"]:
                logger.info(
                    f"[Semantic Cache] ⚡ Cache HIT ({matched_obj['similarity'] * 100:.1f}%)! "
                    f"Queried: '{question.strip()}' -> Matched: '{matched_obj['matchedQuestion']}'"
                )
            else:
                logger.info(
                    f"[Semantic Cache] Candidate found ({matched_obj['similarity'] * 100:.1f}% < {threshold * 100:.0f}%): "
                    f"'{matched_obj['matchedQuestion']}'"
                )

            return matched_obj

    except Exception as e:
        logger.warning(f"[Semantic Cache] Lookup error: {e}")
        return None
    return None

async def clear_query_cache(repo_path: Optional[str] = None) -> dict:
    try:
        coll = get_queries_collection()
        if repo_path:
            coll.delete(where={"repoPath": repo_path})
        else:
            c = get_chroma_client()
            c.delete_collection("reposage_queries")
            global _queries_collection
            _queries_collection = None
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
