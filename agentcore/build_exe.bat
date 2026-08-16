@echo off
setlocal
title AgentCore Build
cd /d "%~dp0"

echo.
echo ============================================
echo   AGENTCORE.EXE BUILDER
echo ============================================
echo.

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

REM === Create .venv if it doesn't exist using supported Python ===
if not exist "%VENV_PY%" (
    echo [setup] AgentCore .venv not found. Creating it...
    
    py -3.12 -m venv "%~dp0.venv" >nul 2>nul
    if errorlevel 1 (
        echo [setup] Python 3.12 not available. Trying Python 3.11...
        py -3.11 -m venv "%~dp0.venv"
        if errorlevel 1 (
            echo [ERROR] No supported Python (3.11 or 3.12) found.
            echo         Please install Python 3.11 or 3.12.
            pause
            exit /b 1
        )
    )
    echo [setup] .venv created successfully.
)

REM === Verify the .venv is using supported Python ===
"%VENV_PY%" -c "import sys; print('Using:', sys.executable); print('Version:', sys.version)" 
"%VENV_PY%" -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,13) else 1)"
if errorlevel 1 (
    echo [ERROR] AgentCore .venv is using an unsupported Python version (must be 3.11 or 3.12).
    pause
    exit /b 1
)

REM === Install dependencies into .venv ===
echo.
echo [setup] Installing dependencies into .venv...
"%VENV_PY%" -m pip install --upgrade pip -q
"%VENV_PY%" -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo [1/3] Running pre-build verification...
"%VENV_PY%" tests\test_build_exe.py
if errorlevel 1 (
    echo.
    echo Build verification failed. Please fix the issues above.
    pause
    exit /b 1
)

echo.
echo [1.5/3] Verifying local imports with project Python...
"%VENV_PY%" -c "import launcher; import voice.manager; print('LOCAL IMPORTS OK')"
if errorlevel 1 (
    echo.
    echo [ERROR] Local module imports failed. Check project structure.
    pause
    exit /b 1
)

echo.
echo [2/3] Starting full build pipeline...
call build.bat

echo.
echo [3/3] Build process finished.
echo.
echo If successful, AgentCore.exe will be in the "dist" folder.
pause
