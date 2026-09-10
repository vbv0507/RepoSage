# RepoSage

RepoSage indexes a repository's source structure, dependency relationships, and recent Git history so that its chat assistant can answer architecture questions with grounded code citations.

## Run with Docker

1. Copy `.env.example` to `.env` and add either `GEMINI_API_KEY` or `OPENAI_API_KEY`. Set `LLM_PROVIDER` to the matching provider.
2. Start Docker Desktop, then run `docker compose up --build` from this directory.
3. Open `http://localhost:3000` and submit a public GitHub URL.

The backend, ChromaDB, and Redis are all started by Docker Compose. The app remains usable with its in-memory cache if Redis is unavailable; an LLM key is required for new chat answers and AI-generated tutorial content.

## Reliability and trust calibration

Source discovery is deterministic and indexes up to 2,000 source files (2 MB per source file). After analysis, open **Index coverage report** in the UI to see every parsed source file, every skipped source file with its reason, excluded directories, parser fallbacks, and whether the limit was reached. A truncated report means RepoSage must not be used to conclude that a module is absent.

`.ragignore` supports simple glob patterns such as `generated/*.py`; excluded paths remain visible in that report. Python files that cannot be parsed as AST are retained as line-based text chunks and marked as parser fallbacks rather than silently discarded.

Cached answers use two safety tiers: a semantic cache hit requires at least 88% similarity in normal use, and an offline fallback requires at least 80%. Below those thresholds RepoSage explicitly reports that no confident answer is available instead of showing an answer to a different question. These are conservative operational thresholds, not a substitute for evaluating the system against your own repository questions.

## Analyze a Windows folder

A Docker container cannot read arbitrary folders on the Windows host. Choose one parent directory to make available, then set it in `.env` before starting the stack:

```env
HOST_REPO_ROOT=C:/Users/your-name/OneDrive/Desktop
```

Restart the stack with `docker compose up --build`. You can then enter any folder below that parent in the UI, for example:

```text
C:\Users\your-name\OneDrive\Desktop\HIVER
```

The mount is read-only. Folders outside `HOST_REPO_ROOT` are deliberately rejected, rather than producing a misleading `/app/C:\...` error.

For a hosted deployment, use **Upload folder** to select a local codebase in your browser (source files only; 25 MB maximum; 2,000 source files maximum), or use a public GitHub URL. The browser filters `node_modules`, build output, and unsupported files before it uploads. A hosted service cannot directly access an arbitrary path on your laptop.

## Local development without Docker

Start the backend from `backend` with an activated virtual environment and `uvicorn main:app --reload --port 5000`, then run `npm run dev` from `frontend`. In this mode the backend runs on Windows and accepts normal Windows paths directly.
