@echo off
REM ============================================================
REM  AgentCore - one-command launcher (Windows)
REM  Bootstraps everything automatically (.venv, deps, playwright,
REM  workspace, database) via main.py, then starts the console.
REM  The ONLY manual prerequisite is installing Python 3.11/3.12
REM  (tick "Add Python to PATH").
REM ============================================================
title AgentCore
cd /d "%~dp0"

REM --- locate Python (try python, then py launcher) ---
set PY=python
python --version >nul 2>nul
if errorlevel 1 (
    py -3 --version >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python 3.11+ not found.
        echo Install it from https://www.python.org/downloads/  (tick "Add Python to PATH").
        pause
        exit /b 1
    )
    set PY=py -3
)

REM --- bootstrap + launch (main.py handles venv/deps/playwright/workspace/db) ---
%PY% main.py
pause
