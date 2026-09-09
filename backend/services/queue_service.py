import time
import os
import asyncio
import logging
from typing import Dict, Any

from .tutorial_generator import get_cached_tutorial, stream_full_tutorial
from .pdf_service import generate_tutorial_pdf
from .mail_service import send_tutorial_email

logger = logging.getLogger("queue_service")

# In-memory store for jobs
_memory_jobs: Dict[str, Dict[str, Any]] = {}

async def _process_email_pdf_job(job_id: str, repo_path: str, email: str):
    job = _memory_jobs.get(job_id)
    if not job:
        return

    def update_progress(pct: int, msg: str):
        job["progress"] = pct
        job["message"] = msg

    try:
        job["state"] = "active"
        update_progress(10, "Retrieving codebase architectural blueprint...")

        # 1. Fetch or generate tutorial
        tutorial = await get_cached_tutorial(repo_path)
        if not tutorial or not tutorial.get("chapters"):
            update_progress(20, "Generating complete architecture documentation via AST + RAG...")
            
            def on_evt(evt):
                if evt.get("step") == "chapter_start":
                    ch_idx = evt.get("chapterIndex", 1)
                    tot = evt.get("totalChapters", 10)
                    pct = 20 + int(((ch_idx - 1) / tot) * 35)
                    update_progress(pct, f"Drafting Chapter {ch_idx}/{tot}: {evt.get('title', '')}...")
                elif evt.get("step") == "chapter_done":
                    ch_idx = evt.get("chapterIndex", 1)
                    tot = evt.get("totalChapters", 10)
                    pct = 20 + int((ch_idx / tot) * 35)
                    update_progress(pct, f"Completed Chapter {ch_idx}/{tot}.")

            tutorial = await stream_full_tutorial(repo_path, on_evt)

        # 2. Compile PDF
        update_progress(60, "Compiling publication-grade PDF blueprint...")
        pdf_bytes = generate_tutorial_pdf(tutorial)

        # 3. Dispatch Email
        update_progress(85, f"Sending documentation PDF to {email}...")
        mail_res = await send_tutorial_email(
            to_email=email,
            repo_name=tutorial.get("repoName", "Repository"),
            pdf_bytes=pdf_bytes
        )

        update_progress(100, "Documentation email delivered successfully!")
        job["state"] = "completed"
        job["result"] = {
            "email": email,
            "repoName": tutorial.get("repoName"),
            "messageId": mail_res.get("messageId"),
            "deliveredAt": time.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}", exc_info=True)
        job["state"] = "failed"
        job["error"] = str(e)
        job["message"] = f"Processing failed: {str(e)}"

async def add_email_pdf_job(repo_path: str, email: str) -> Dict[str, Any]:
    job_id = f"mem_{int(time.time() * 1000)}_{os.urandom(3).hex()}"
    job_state = {
        "id": job_id,
        "state": "waiting",
        "progress": 0,
        "message": "Job queued in background worker...",
        "data": {"repoPath": repo_path, "email": email},
        "result": None,
        "error": None,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ")
    }

    _memory_jobs[job_id] = job_state

    # Launch background task
    asyncio.create_task(_process_email_pdf_job(job_id, repo_path, email))

    return {
        "jobId": job_id,
        "queueType": "Worker Queue (Async Python)"
    }

async def get_job_status(job_id: str) -> Dict[str, Any]:
    job = _memory_jobs.get(job_id)
    if not job:
        return {
            "id": job_id,
            "state": "failed",
            "progress": 0,
            "message": "Job not found.",
            "result": None,
            "error": "Job not found"
        }
    return {
        "id": job["id"],
        "state": job["state"],
        "progress": job["progress"],
        "message": job["message"],
        "result": job["result"],
        "error": job["error"]
    }
