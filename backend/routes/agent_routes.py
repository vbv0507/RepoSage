"""
agent_routes.py � Spider AI Agent API for RepoSage

Exposes authenticated, LLM-friendly JSON endpoints that Spider AI (portfolio chatbot)
can call to query codebases, check ChromaDB/Redis status, and trigger AST indexing.

Auth: Requires 'x-agent-token' header matching AGENT_SECRET env var.
Mounted at: /api/agent (in main.py)
"""

import os
import hmac
import logging
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Header, HTTPException, status, Depends, Query
from pydantic import BaseModel

logger = logging.getLogger("reposage_agent")

router = APIRouter(tags=["Agent Control Plane"])

# --- Security Dependency ---
def verify_agent_token(x_agent_token: Optional[str] = Header(None)) -> bool:
    secret = os.getenv("AGENT_SECRET", "")
    if not x_agent_token or not secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing agent token"
        )
    if not hmac.compare_digest(x_agent_token, secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid agent token"
        )
    return True

# --- Request Models ---
class AgentQueryRequest(BaseModel):
    question: str
    repoPath: Optional[str] = None
    refresh: Optional[bool] = False

class AgentIngestRequest(BaseModel):
    repoPath: str
    force: Optional[bool] = False

# --- Helper to list available repos ---
def list_available_repos() -> List[Dict[str, Any]]:
    repos = []
    clone_base = os.path.abspath("./cloned_repos")
    if os.path.exists(clone_base):
        for entry in os.listdir(clone_base):
            full = os.path.join(clone_base, entry)
            if os.path.isdir(full):
                repos.append({
                    "name": entry,
                    "path": full,
                    "type": "cloned"
                })
    return repos

# --- Endpoints ---

@router.get("/ping", dependencies=[Depends(verify_agent_token)])
async def agent_ping():
    """Connectivity & readiness probe for Spider AI."""
    from services.redis_service import cache_service
    from services.chroma_service import check_chroma_connection
    from services.llm_provider import check_config_status

    chroma = await asyncio.to_thread(check_chroma_connection)
    redis_status = cache_service.get_status()
    llm = check_config_status()

    return {
        "success": True,
        "service": "reposage-agent-api",
        "status": "online",
        "engine": "FastAPI + Tree-sitter + Dual-Collection ChromaDB",
        "services": {
            "redis": redis_status,
            "chroma": chroma,
            "llm": llm
        }
    }

@router.get("/status", dependencies=[Depends(verify_agent_token)])
async def agent_status():
    """Live state: ChromaDB vector collections, cache, and indexed repositories."""
    from services.chroma_service import (
        get_code_collection,
        get_diffs_collection,
        get_queries_collection,
        check_chroma_connection
    )
    from services.redis_service import cache_service
    from services.llm_provider import check_config_status

    def get_counts():
        counts = {}
        try:
            from services.chroma_service import get_chroma_client
            client = get_chroma_client()
            for c in client.list_collections():
                counts[c.name] = c.count()
        except Exception as e:
            counts["error"] = str(e)
        return counts

    counts = await asyncio.to_thread(get_counts)
    repos = list_available_repos()

    return {
        "success": True,
        "collections": counts,
        "availableRepos": repos,
        "cache": cache_service.get_status(),
        "llm": check_config_status(),
        "chroma": await asyncio.to_thread(check_chroma_connection)
    }

@router.get("/repos", dependencies=[Depends(verify_agent_token)])
async def agent_list_repos():
    """List all repositories available for querying or already cloned."""
    repos = list_available_repos()
    return {
        "success": True,
        "count": len(repos),
        "repos": repos
    }

@router.post("/query", dependencies=[Depends(verify_agent_token)])
async def agent_query_codebase(req: AgentQueryRequest):
    """
    Execute an architectural question across an indexed codebase.
    Returns synthesized answer, code citations, and confidence level.
    """
    from services.rag_service import resolve_repo_path, query_codebase

    target_repo = req.repoPath
    if not target_repo:
        repos = list_available_repos()
        if repos:
            target_repo = repos[0]["path"]
        else:
            raise HTTPException(
                status_code=400,
                detail="No repoPath provided and no cloned repos found."
            )

    try:
        resolved = resolve_repo_path(target_repo)
        result = await query_codebase(
            repo_path=resolved,
            question=req.question,
            refresh=bool(req.refresh)
        )

        return {
            "success": True,
            "question": req.question,
            "repoPath": resolved,
            "answer": result.get("answer") or result.get("text", ""),
            "confidenceLevel": result.get("confidenceLevel", "MEDIUM"),
            "codeCitations": (result.get("codeCitations") or [])[:5],
            "gitCitations": (result.get("gitCitations") or [])[:3],
            "fromCache": result.get("fromCache", False),
            "semanticCache": result.get("semanticCache", False)
        }
    except Exception as e:
        logger.error(f"[Agent Query Error]: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ingest", dependencies=[Depends(verify_agent_token)])
async def agent_ingest(req: AgentIngestRequest):
    """Trigger AST parsing and dual-collection vector embedding for a repository."""
    from services.rag_service import resolve_repo_path, ingest_codebase

    try:
        resolved = resolve_repo_path(req.repoPath)
        stats = await ingest_codebase(resolved, force_refresh=bool(req.force))
        return {
            "success": True,
            "message": "Repository successfully indexed.",
            "resolvedPath": resolved,
            "stats": stats
        }
    except Exception as e:
        logger.error(f"[Agent Ingest Error]: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/graph", dependencies=[Depends(verify_agent_token)])
async def agent_graph(path: str = Query(..., description="Repository path")):
    """Fetch module dependency graph from cache."""
    from services.rag_service import resolve_repo_path
    from services.redis_service import cache_service

    try:
        resolved = resolve_repo_path(path)
        graph = await cache_service.get(f"graph:{resolved}")
        return {
            "success": True,
            "repoPath": resolved,
            "graph": graph or {"nodes": [], "links": []}
        }
    except Exception as e:
        logger.error(f"[Agent Graph Error]: {e}")
        raise HTTPException(status_code=500, detail=str(e))


