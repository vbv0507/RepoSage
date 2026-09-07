@echo off
title RepoSage - ChromaDB Server (Port 8000)
echo ========================================================
echo Starting local ChromaDB Vector Database for RepoSage...
echo ========================================================
echo.

if not exist "chroma_data" mkdir "chroma_data"

set "USER_SCRIPTS=%APPDATA%\Python\Python314\Scripts"
if exist "%USER_SCRIPTS%" set "PATH=%USER_SCRIPTS%;%PATH%"

where chroma >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [INFO] Starting Chroma on http://localhost:8000 with storage in ./chroma_data
    chroma run --path ./chroma_data --port 8000
    goto end
)

if exist "%APPDATA%\Python\Python314\Scripts\chroma.exe" (
    echo [INFO] Starting Chroma using %APPDATA%\Python\Python314\Scripts\chroma.exe
    "%APPDATA%\Python\Python314\Scripts\chroma.exe" run --path ./chroma_data --port 8000
    goto end
)

echo [ERROR] Chroma executable not found. Run: python -m pip install chromadb
pause

:end
