import os
import json
import asyncio
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("reposage_backend")

from services.redis_service import cache_service
from services.chroma_service import check_chroma_connection
from services.llm_provider import check_config_status
from services.rag_service import resolve_repo_path, ingest_codebase, query_codebase
from services.tutorial_generator import stream_full_tutorial, get_cached_tutorial
from services.queue_service import add_email_pdf_job, get_job_status

app = FastAPI(
    title="RepoSage AI Engine",
    description="Principal Software Architect AI - Dual-Collection RAG & Code Intelligence",
    version="2.0.0"
)

# Enable CORS for React frontend & browser extensions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request Models
class IngestRequest(BaseModel):
    repoPath: str
    force: Optional[bool] = False

class ChatRequest(BaseModel):
    repoPath: Optional[str] = None
    question: str
    refresh: Optional[bool] = False

class TutorialExportRequest(BaseModel):
    repoPath: str

class EmailPdfRequest(BaseModel):
    repoPath: str
    email: str

@app.get("/api/health")
async def health_check():
    chroma = check_chroma_connection()
    redis_status = cache_service.get_status()
    llm = check_config_status()

    return {
        "status": "ok",
        "engine": "Python (FastAPI + LangChain)",
        "services": {
            "redis": redis_status,
            "chroma": chroma,
            "llm": llm
        }
    }

@app.get("/api/ingest-stream")
async def ingest_stream(
    path: str = Query(..., description="Local folder path or GitHub repository URL"),
    force: Optional[bool] = Query(False),
    refresh: Optional[bool] = Query(False)
):
    force_refresh = force or refresh

    async def event_generator():
        queue = asyncio.Queue()

        def on_progress(data: dict):
            queue.put_nowait(data)

        async def worker():
            try:
                resolved = resolve_repo_path(path, on_progress=on_progress)
                on_progress({"step": "start", "message": f"Starting analysis for: {resolved}"})
                stats = await ingest_codebase(resolved, on_progress=on_progress, force_refresh=force_refresh)
                on_progress({"step": "finished", "stats": stats, "resolvedPath": resolved})
            except Exception as e:
                logger.error(f"Ingest stream error: {e}", exc_info=True)
                on_progress({"step": "error", "error": str(e)})
            finally:
                on_progress({"__done__": True})

        task = asyncio.create_task(worker())

        while True:
            item = await queue.get()
            if "__done__" in item:
                break
            yield f"data: {json.dumps(item)}\n\n"

        await task

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )

@app.post("/api/ingest")
async def ingest_endpoint(req: IngestRequest):
    try:
        resolved = resolve_repo_path(req.repoPath)
        stats = await ingest_codebase(resolved, force_refresh=bool(req.force))
        return {"success": True, "stats": stats, "resolvedPath": resolved}
    except Exception as e:
        logger.error(f"Ingest error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    try:
        resolved = resolve_repo_path(req.repoPath) if req.repoPath else None
        response = await query_codebase(
            repo_path=resolved,
            question=req.question,
            refresh=bool(req.refresh)
        )
        return response
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/graph")
async def graph_endpoint(path: str = Query(..., description="Repository path or URL")):
    try:
        resolved = resolve_repo_path(path)
        graph = await cache_service.get(f"graph:{resolved}")
        return graph or {"nodes": [], "links": []}
    except Exception as e:
        logger.error(f"Graph error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tutorial-stream")
async def tutorial_stream(
    path: str = Query(..., description="Repository path or URL"),
    refresh: Optional[bool] = Query(False)
):
    async def event_generator():
        queue = asyncio.Queue()

        def on_event(data: dict):
            queue.put_nowait(data)

        async def worker():
            try:
                resolved = resolve_repo_path(path)
                if refresh:
                    await cache_service.delete(f"tutorial:{resolved}")
                await stream_full_tutorial(resolved, on_event=on_event)
            except Exception as e:
                logger.error(f"Tutorial stream error: {e}", exc_info=True)
                on_event({"step": "error", "error": str(e)})
            finally:
                on_event({"__done__": True})

        task = asyncio.create_task(worker())

        while True:
            item = await queue.get()
            if "__done__" in item:
                break
            yield f"data: {json.dumps(item)}\n\n"

        await task

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )

@app.get("/api/tutorial")
async def get_tutorial(path: str = Query(...)):
    try:
        resolved = resolve_repo_path(path)
        cached = await get_cached_tutorial(resolved)
        if not cached:
            raise HTTPException(status_code=404, detail="No tutorial generated yet for this repository.")
        return cached
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tutorial/export")
async def export_tutorial(req: TutorialExportRequest):
    try:
        resolved = resolve_repo_path(req.repoPath)
        cached = await get_cached_tutorial(resolved)
        if not cached or not cached.get("fullMarkdown"):
            raise HTTPException(status_code=404, detail="Please generate the tutorial first before exporting.")

        repo_name = cached.get("repoName", "architecture")
        filename = f"{repo_name}_tutorial.md"
        
        return Response(
            content=cached["fullMarkdown"],
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/tutorial/cache")
async def clear_tutorial_cache(path: str = Query(...)):
    try:
        resolved = resolve_repo_path(path)
        await cache_service.delete(f"tutorial:{resolved}")
        return {"success": True, "message": f"Cache cleared for {resolved}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tutorial/email")
async def email_tutorial_endpoint(req: EmailPdfRequest):
    try:
        resolved = resolve_repo_path(req.repoPath)
        job_info = await add_email_pdf_job(repo_path=resolved, email=req.email)
        return {
            "success": True,
            "jobId": job_info["jobId"],
            "queueType": job_info["queueType"],
            "message": f"PDF generation and email dispatch queued in {job_info['queueType']}."
        }
    except Exception as e:
        logger.error(f"Email queue error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tutorial/email/status/{job_id}")
async def job_status_endpoint(job_id: str):
    try:
        status = await get_job_status(job_id)
        return status
    except Exception as e:
        logger.error(f"Job status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "5000"))
    logger.info(f"🚀 Starting RepoSage Python FastAPI Backend on http://localhost:{port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
