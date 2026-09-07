@echo off
title RepoSage Development Launcher
echo ========================================================
echo Launching RepoSage (Backend on 5000, Frontend on 3000)
echo ========================================================
echo.

start "RepoSage Backend" cmd /k "cd backend && npm start"
start "RepoSage Frontend" cmd /k "cd frontend && npm run dev"

echo Both services launched!
echo - Backend: http://localhost:5000
echo - Frontend: http://localhost:3000
pause
