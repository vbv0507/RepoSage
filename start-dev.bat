@echo off
title RepoSage Development Launcher
echo ========================================================
echo Launching RepoSage (Backend on 7860, Frontend on 5173)
echo ========================================================
echo.

start "RepoSage Backend (Python FastAPI)" cmd /k "cd backend && call .venv\Scripts\activate && uvicorn main:app --host 0.0.0.0 --port 7860 --reload"
start "RepoSage Frontend" cmd /k "cd frontend && npm run dev"

echo Both services launched!
echo - Python Backend: http://localhost:7860
echo - React Frontend: http://localhost:5173
pause

