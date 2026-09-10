import os
import json
import asyncio
import logging
import shutil
import uuid
from pathlib import PurePosixPath
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.datastructures import UploadFile as StarletteUploadFile
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("reposage_backend")

from services.redis_service import cache_service
from services.chroma_service import check_chroma_connection
from services.llm_provider import check_config_status
from services.ast_parser import CODE_EXTENSIONS, IGNORED_DIRS, is_ignored_file
from services.rag_service import UPLOAD_REPO_PREFIX, resolve_repo_path, ingest_codebase, query_codebase
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

MAX_UPLOAD_FILES = 2000
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _safe_uploaded_file_path(filename: str) -> Optional[PurePosixPath]:
    """Accept only safe, parseable source files from a browser folder upload."""
    if not filename:
        return None
    candidate = PurePosixPath(filename.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts or len(candidate.parts) > 20:
        return None
    if any(part in IGNORED_DIRS or part.startswith(".") for part in candidate.parts[:-1]):
        return None
    basename = candidate.name
    extension = candidate.suffix.lower()
    if is_ignored_file(basename) or not (extension in CODE_EXTENSIONS or basename in {"Dockerfile", "Makefile"}):
        return None
    return candidate

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


@app.post("/api/upload-repository")
async def upload_repository(request: Request):
    """Store a browser-selected source folder for analysis in this app instance.

    The API intentionally accepts source/configuration files only, limits its
    size, and treats submitted names as relative paths to prevent traversal.
    """
    try:
        form = await request.form(max_files=MAX_UPLOAD_FILES, max_part_size=MAX_UPLOAD_BYTES)
    except Exception as exc:
        raise HTTPException(status_code=413, detail="Upload has too many files or a file exceeds the allowed size.") from exc

    files = [file for file in form.getlist("files") if isinstance(file, StarletteUploadFile)]
    if not files:
        raise HTTPException(status_code=400, detail="Choose a folder containing source files first.")
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=413, detail=f"Upload at most {MAX_UPLOAD_FILES} files at a time.")

    upload_root = os.path.abspath(os.getenv("UPLOAD_REPO_ROOT", "/tmp/reposage_uploads"))
    upload_id = str(uuid.uuid4())
    destination = os.path.join(upload_root, upload_id)
    stored_count = 0
    total_bytes = 0

    try:
        for uploaded in files:
            relative_path = _safe_uploaded_file_path(uploaded.filename or "")
            if not relative_path:
                continue
            target = os.path.abspath(os.path.join(destination, *relative_path.parts))
            if os.path.commonpath([destination, target]) != destination:
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as output:
                while chunk := await uploaded.read(1024 * 1024):
                    total_bytes += len(chunk)
                    if total_bytes > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="Source upload exceeds the 25 MB limit.")
                    output.write(chunk)
            stored_count += 1
    except HTTPException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(destination, ignore_errors=True)
        logger.error("Repository upload failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not store the uploaded folder.") from exc
    finally:
        for uploaded in files:
            await uploaded.close()

    if not stored_count:
        shutil.rmtree(destination, ignore_errors=True)
        raise HTTPException(status_code=400, detail="No supported source files were found in that folder.")

    return {
        "success": True,
        "repoPath": f"{UPLOAD_REPO_PREFIX}{upload_id}",
        "filesCount": stored_count,
        "message": "Folder uploaded. Starting analysis is now safe to do."
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
        event_loop = asyncio.get_running_loop()

        def on_progress(data: dict):
            # Analysis runs outside the event loop because Git, ChromaDB, and
            # embeddings use blocking clients. This bridge is thread-safe.
            event_loop.call_soon_threadsafe(queue.put_nowait, data)

        async def worker():
            try:
                def run_analysis():
                    resolved = resolve_repo_path(path, on_progress=on_progress)
                    on_progress({"step": "start", "message": f"Starting analysis for: {resolved}"})
                    stats = asyncio.run(
                        ingest_codebase(resolved, on_progress=on_progress, force_refresh=force_refresh)
                    )
                    on_progress({"step": "finished", "stats": stats, "resolvedPath": resolved})

                # Keep the ASGI event loop free so the SSE stream can emit
                # heartbeats while a forced re-index is embedding code.
                await asyncio.to_thread(run_analysis)
            except Exception as e:
                logger.error(f"Ingest stream error: {e}", exc_info=True)
                on_progress({"step": "error", "error": str(e)})
            finally:
                on_progress({"__done__": True})

        task = asyncio.create_task(worker())

        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=10)
            except asyncio.TimeoutError:
                # Prevent Azure/NGINX idle connection timeouts during a long
                # vector batch. SSE comments are ignored by the UI.
                yield ": keep-alive\n\n"
                continue
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
