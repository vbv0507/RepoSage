---
title: RepoSage API
emoji: "🔎"
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# RepoSage API

FastAPI backend for a Hugging Face Docker Space.

Set these Space secrets before starting the Space:

- `GEMINI_API_KEY` or `OPENAI_API_KEY`
- `AGENT_SECRET` for trusted server-to-server `/api/agent` calls
- `ALLOWED_ORIGINS` with the exact Vercel frontend origin

The Space uses ephemeral local Chroma storage at `/tmp/chroma`. When the
database is empty, RepoSage starts a small sample-repository index in the
background without delaying `/health`.
