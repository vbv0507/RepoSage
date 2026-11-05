# RepoSage API

FastAPI backend for a Render free Docker web service.

Set these Render environment variables before deploying:

- `GEMINI_API_KEY` or `OPENAI_API_KEY`
- `AGENT_SECRET` for trusted server-to-server `/api/agent` calls
- `ALLOWED_ORIGINS` with the exact Vercel frontend origin
- `SEMANTIC_CACHE=off` to avoid loading the local MiniLM model on Render Free

Render uses ephemeral local Chroma storage at `/tmp/chroma`. When the
database is empty, RepoSage starts a small sample-repository index in the
background without delaying `/health`.

Render runs the container command in `Dockerfile` and supplies `PORT`; the
container falls back to port 7860 for local use.
