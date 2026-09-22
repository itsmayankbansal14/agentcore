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

REM === Create .venv if it doesn't exist using Python 3.12 ===
if not exist "%VENV_PY%" (
    echo [setup] AgentCore .venv not found. Creating it with Python 3.12...

    py -3.12 -m venv "%~dp0.venv"
    if errorlevel 1 (
        echo [ERROR] Python 3.12 not found.
        echo         AgentCore REQUIRES Python 3.12 (not 3.11, not 3.13+).
        echo         Please install Python 3.12 from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo [setup] .venv created successfully with Python 3.12.
)

REM === Verify the .venv is using Python 3.12 ===
"%VENV_PY%" -c "import sys; print('Using:', sys.executable); print('Version:', sys.version)"
"%VENV_PY%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
if errorlevel 1 (
    echo [ERROR] AgentCore .venv is NOT using Python 3.12.
    echo         Current version is incompatible.
    echo         Delete .venv folder and run this script again to create with Python 3.12.
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
set "PYTHON=%VENV_PY%"
call build.bat

echo.
echo [3/3] Build process finished.
echo.
echo If successful, AgentCore.exe will be in the "dist" folder.
pause
