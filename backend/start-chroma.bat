@echo off
title RepoSage - ChromaDB Server (Port 8000)
echo ========================================================
echo Starting local ChromaDB Vector Database for RepoSage...
echo ========================================================
echo.

if not exist "chroma_data" mkdir "chroma_data"

where chroma >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [INFO] Starting Chroma on http://localhost:8000 with storage in ./chroma_data
    chroma run --path ./chroma_data --port 8000
    goto end
)

python -c "import chromadb" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [INFO] ChromaDB module detected, starting via python CLI...
    python -m chromadb.cli.cli run --path ./chroma_data --port 8000
    goto end
)

echo [ERROR] ChromaDB is not installed or not in PATH.
echo.
echo To install ChromaDB locally, run:
echo   pip install chromadb
echo.
echo Or run via Docker:
echo   docker run -d -p 8000:8000 -v "%cd%/chroma_data:/chroma/chroma" chromadb/chroma
echo.
pause

:end
