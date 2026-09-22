@echo off
REM ============================================================
REM  AgentCore Environment Validation Script
REM  Run this to verify environment before hardware testing
REM ============================================================
setlocal enabledelayedexpansion
title AgentCore Environment Validation
cd /d "%~dp0"

echo.
echo ========================================================
echo   AGENTCORE ENVIRONMENT VALIDATION
echo   Date: %DATE% %TIME%
echo ========================================================
echo.

set "ERRORS=0"
set "WARNINGS=0"

REM ============================================================
REM  CHECK 1: Python Version (MUST be 3.12)
REM ============================================================
echo [1/8] Checking Python version...
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PATH_PYTHON_VERSION=%%i
echo   PATH Python: !PATH_PYTHON_VERSION!
py -3.12 --version >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] Python 3.12 was not found. AgentCore requires Python 3.12 ONLY
    set /a ERRORS+=1
) else (
    for /f "tokens=2" %%i in ('py -3.12 --version 2^>^&1') do set PYTHON_VERSION=%%i
    echo   [PASS] Python launcher: !PYTHON_VERSION!
)

REM ============================================================
REM  CHECK 2: Virtual Environment
REM ============================================================
:check_venv
echo.
echo [2/8] Checking virtual environment...
if exist ".venv\Scripts\python.exe" (
    echo   [PASS] .venv exists at: %~dp0.venv

    REM Check .venv Python version
    for /f "tokens=2" %%i in ('".venv\Scripts\python.exe" --version 2^>^&1') do set VENV_VERSION=%%i
    echo   .venv Python: !VENV_VERSION!

    REM Extract major.minor for venv
    for /f "tokens=1,2 delims=." %%a in ("!VENV_VERSION!") do (
        set VENV_MAJOR=%%a
        set VENV_MINOR=%%b
    )

    if "!VENV_MAJOR!"=="3" (
        if "!VENV_MINOR!"=="12" (
            echo   [PASS] .venv using Python 3.12
        ) else (
            echo   [FAIL] .venv using Python 3.!VENV_MINOR! - AgentCore requires 3.12 ONLY
            set /a ERRORS+=1
        )
    )
) else (
    echo   [WARN] .venv not found - bootstrap will create it
    set /a WARNINGS+=1
)

REM ============================================================
REM  CHECK 3: Critical Dependencies
REM ============================================================
echo.
echo [3/8] Checking critical dependencies...
set "PY_CMD=python"
if exist ".venv\Scripts\python.exe" set "PY_CMD=.venv\Scripts\python.exe"

echo   Using: %PY_CMD%

REM Test imports
"%PY_CMD%" -c "import structlog" >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] structlog not installed
    set /a ERRORS+=1
) else (
    echo   [PASS] structlog
)

"%PY_CMD%" -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] fastapi not installed
    set /a ERRORS+=1
) else (
    echo   [PASS] fastapi
)

"%PY_CMD%" -c "import sqlalchemy" >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] sqlalchemy not installed
    set /a ERRORS+=1
) else (
    echo   [PASS] sqlalchemy
)

"%PY_CMD%" -c "import openai" >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] openai not installed
    set /a ERRORS+=1
) else (
    echo   [PASS] openai
)

REM ============================================================
REM  CHECK 4: Voice Dependencies
REM ============================================================
echo.
echo [4/8] Checking voice dependencies...

"%PY_CMD%" -c "import faster_whisper" >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] faster-whisper not installed ^(STT will not work^)
    set /a ERRORS+=1
) else (
    echo   [PASS] faster-whisper ^(STT^)
)

"%PY_CMD%" -c "import edge_tts" >nul 2>&1
if errorlevel 1 (
    echo   [WARN] edge-tts not installed ^(TTS may not work^)
    set /a WARNINGS+=1
) else (
    echo   [PASS] edge-tts ^(TTS^)
)

"%PY_CMD%" -c "import sounddevice" >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] sounddevice not installed ^(microphone will not work^)
    set /a ERRORS+=1
) else (
    echo   [PASS] sounddevice ^(microphone^)
)

REM ============================================================
REM  CHECK 5: Configuration
REM ============================================================
echo.
echo [5/8] Checking configuration...
if exist "config\defaults.yaml" (
    findstr /C:"stt_language: auto" config\defaults.yaml >nul 2>&1
    if errorlevel 1 (
        echo   [WARN] stt_language: auto not found in config
        set /a WARNINGS+=1
    ) else (
        echo   [PASS] Multilingual STT configuration detected
    )

    findstr /R /C:"^[ ]*whisper_model: base.en" config\defaults.yaml >nul 2>&1
    if not errorlevel 1 (
        echo   [WARN] Old English-only whisper model setting is still present
        set /a WARNINGS+=1
    )
) else (
    echo   [FAIL] config\defaults.yaml not found
    set /a ERRORS+=1
)

REM ============================================================
REM  CHECK 6: Project Structure
REM ============================================================
echo.
echo [6/8] Checking project structure...

set "REQUIRED_FILES=main.py launcher.py bootstrap.py config\defaults.yaml requirements.txt"
set "MISSING_FILES="

for %%f in (%REQUIRED_FILES%) do (
    if not exist "%%f" (
        echo   [FAIL] Missing: %%f
        set "MISSING_FILES=!MISSING_FILES! %%f"
        set /a ERRORS+=1
    )
)

if "!MISSING_FILES!"=="" (
    echo   [PASS] All required files present
)

set "REQUIRED_DIRS=core voice config database devices executor planner"
set "MISSING_DIRS="

for %%d in (%REQUIRED_DIRS%) do (
    if not exist "%%d\" (
        echo   [FAIL] Missing directory: %%d
        set "MISSING_DIRS=!MISSING_DIRS! %%d"
        set /a ERRORS+=1
    )
)

if "!MISSING_DIRS!"=="" (
    echo   [PASS] All required directories present
)

REM ============================================================
REM  CHECK 7: Audio Devices
REM ============================================================
echo.
echo [7/8] Checking audio devices...
"%PY_CMD%" -c "import sounddevice; sounddevice.query_devices^()" >nul 2>&1
if errorlevel 1 (
    echo   [WARN] Cannot query audio devices
    set /a WARNINGS+=1
) else (
    echo   [PASS] Audio devices can be queried
)

REM ============================================================
REM  CHECK 8: Documentation
REM ============================================================
echo.
echo [8/8] Checking documentation...
if exist "STATUS.md" (
    echo   [PASS] STATUS.md found
) else (
    echo   [WARN] STATUS.md missing ^(not critical^)
)

if exist "VALIDATION.md" (
    echo   [PASS] VALIDATION.md found
) else (
    echo   [WARN] VALIDATION.md missing ^(not critical^)
)

if exist "CHANGES.md" (
    echo   [PASS] CHANGES.md found
) else (
    echo   [WARN] CHANGES.md missing ^(not critical^)
)

REM ============================================================
REM  SUMMARY
REM ============================================================
echo.
echo ========================================================
echo   VALIDATION SUMMARY
echo ========================================================
echo   Errors:   !ERRORS!
echo   Warnings: !WARNINGS!
echo ========================================================

if !ERRORS! GTR 0 (
    echo.
    echo   [FAIL] Environment is NOT READY
    echo.
    echo   Fix the errors above, then run this script again.
    echo   For detailed guidance, see VALIDATION.md
    echo.
    exit /b 1
) else if !WARNINGS! GTR 0 (
    echo.
    echo   [PASS] Environment is READY with minor warnings
    echo.
    echo   You can proceed with voice testing, but review warnings above.
    echo.
    exit /b 0
) else (
    echo.
    echo   [PASS] Environment is READY
    echo.
    echo   Next step: Run voice validation
    echo   Command: Launch_AgentCore.bat
    echo   Then speak: "What time is it?"
    echo.
    exit /b 0
)
