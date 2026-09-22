@echo off
REM Single-click source launcher: validate, then start dashboard + tray + voice.
setlocal
cd /d "%~dp0"
title AgentCore

py -3.12 --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.12 is required. Install it from python.org first.
    pause
    exit /b 1
)

call validate_env.bat
if errorlevel 1 (
    echo.
    echo [ERROR] Validation failed. Resolve the reported issue before launch.
    pause
    exit /b 1
)

echo.
echo Starting AgentCore...
REM main.py bootstraps the project venv on first launch, then starts the
REM dashboard, system tray, and persistent voice runtime on the same app.
py -3.12 main.py --launcher
if errorlevel 1 pause
