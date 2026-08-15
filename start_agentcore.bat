@echo off
REM ============================================================
REM  AgentCore - One-click launcher (Windows)
REM  Double-click this file to start the dashboard + open browser
REM ============================================================
title AgentCore Dashboard
cd /d "%~dp0"

echo.
echo  ============================================
echo    AGENTCORE  -  starting your AI agent...
echo  ============================================
echo.

REM --- check Python ---
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Install it from https://www.python.org/downloads/
    echo IMPORTANT: tick "Add Python to PATH" during install.
    pause
    exit /b 1
)

REM --- install deps on first run (or if missing) ---
python -c "import flask, fastapi, sqlalchemy, structlog" >nul 2>nul
if errorlevel 1 (
    echo [setup] Installing dependencies (first run only)...
    pip install -r requirements.txt
)

REM --- start the agent + open the browser ---
echo [ok] Starting dashboard at http://localhost:8000
start "" http://localhost:8000
python main.py serve

pause
