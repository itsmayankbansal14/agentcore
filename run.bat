@echo off
REM ============================================================
REM  run.bat — Clean-machine launcher
REM  Finds Python 3.12, then delegates to main.py which handles
 REM  venv creation, dep install, playwright, and app launch.
REM  No manual steps required.
REM ============================================================
setlocal

REM Prefer py launcher (Windows), fall back to python
where py >nul 2>&1 && set PY=py -3.12 || set PY=python

%PY% --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.12 not found. Install from https://python.org/downloads/
    pause
    exit /b 1
)

%PY% main.py
if errorlevel 1 pause
