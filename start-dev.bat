@echo off
title RepoSage Development Launcher
echo ========================================================
echo Launching RepoSage (Backend on 5000, Frontend on 3000)
echo ========================================================
echo.

start "RepoSage Backend (Python FastAPI)" cmd /k "cd backend && call .venv\Scripts\activate && uvicorn main:app --host 0.0.0.0 --port 5000 --reload"
start "RepoSage Frontend" cmd /k "cd frontend && npm run dev"

echo Both services launched!
echo - Python Backend: http://localhost:5000
echo - React Frontend: http://localhost:3000
pause
