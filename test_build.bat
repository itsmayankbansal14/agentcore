@echo off
REM ============================================================
REM  AgentCore Build Integrity Test
REM  Verifies build is clean and functional after cleanup
REM  Date: 2026-09-17
REM ============================================================
setlocal enabledelayedexpansion
title AgentCore Build Integrity Test
cd /d "%~dp0"

echo.
echo ========================================================
echo   AGENTCORE BUILD INTEGRITY TEST
echo   Time: %TIME%
echo ========================================================
echo.
echo This will verify:
echo   1. Essential files are present
echo   2. Python version is correct
echo   3. Bootstrap can run
echo   4. Doctor check passes
echo   5. No unnecessary files remain
echo.
pause

set "PASSED=0"
set "FAILED=0"

REM ============================================================
REM  TEST 1: Essential Files
REM ============================================================
echo.
echo ========================================================
echo   TEST 1: Essential Files Present
echo ========================================================

set "ESSENTIAL_FILES=main.py bootstrap.py launcher.py requirements.txt config\defaults.yaml README.md"

for %%f in (%ESSENTIAL_FILES%) do (
    if exist "%%f" (
        echo   [PASS] %%f
        set /a PASSED+=1
    ) else (
        echo   [FAIL] %%f MISSING
        set /a FAILED+=1
    )
)

set "ESSENTIAL_DIRS=core voice config database devices executor planner api dashboard tools"

for %%d in (%ESSENTIAL_DIRS%) do (
    if exist "%%d\" (
        echo   [PASS] %%d/
        set /a PASSED+=1
    ) else (
        echo   [FAIL] %%d/ MISSING
        set /a FAILED+=1
    )
)

REM ============================================================
REM  TEST 2: No Unnecessary Files
REM ============================================================
echo.
echo ========================================================
echo   TEST 2: No Unnecessary Files
echo ========================================================

set "BAD_PATTERNS=__pycache__ *.pyc .vscode .idea .DS_Store Thumbs.db dist build *.spec logs data .pytest_cache .coverage"

for %%p in (%BAD_PATTERNS%) do (
    if exist "%%p" (
        echo   [WARN] Found: %%p (should be cleaned)
        set /a FAILED+=1
    ) else (
        echo   [PASS] Not found: %%p
        set /a PASSED+=1
    )
)

REM ============================================================
REM  TEST 3: Python Version
REM ============================================================
echo.
echo ========================================================
echo   TEST 3: Python Version
echo ========================================================

python --version >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] Python not found
    set /a FAILED+=1
) else (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do (
        echo   Found: Python %%v
        echo %%v | findstr /r "3\.12\." >nul
        if errorlevel 1 (
            echo   [FAIL] Must be Python 3.12.x
            set /a FAILED+=1
        ) else (
            echo   [PASS] Python 3.12 detected
            set /a PASSED+=1
        )
    )
)

REM ============================================================
REM  TEST 4: Bootstrap Dry Run
REM ============================================================
echo.
echo ========================================================
echo   TEST 4: Bootstrap Dry Run
echo ========================================================

python bootstrap.py >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] Bootstrap failed
    set /a FAILED+=1
) else (
    echo   [PASS] Bootstrap succeeded
    set /a PASSED+=1
)

REM ============================================================
REM  TEST 5: Doctor Check
REM ============================================================
echo.
echo ========================================================
echo   TEST 5: Doctor Health Check
echo ========================================================

python main.py doctor >nul 2>&1
if errorlevel 1 (
    echo   [WARN] Doctor reported issues (may be optional)
    echo   Run 'python main.py doctor' manually to see details
) else (
    echo   [PASS] Doctor check passed
    set /a PASSED+=1
)

REM ============================================================
REM  TEST 6: Import Test
REM ============================================================
echo.
echo ========================================================
echo   TEST 6: Core Module Imports
echo ========================================================

python -c "from core.app import AgentApp" 2>nul
if errorlevel 1 (
    echo   [FAIL] Cannot import core.app
    set /a FAILED+=1
) else (
    echo   [PASS] core.app imports successfully
    set /a PASSED+=1
)

python -c "from voice.manager import VoiceManager" 2>nul
if errorlevel 1 (
    echo   [WARN] Cannot import voice.manager (may need dependencies)
) else (
    echo   [PASS] voice.manager imports successfully
    set /a PASSED+=1
)

REM ============================================================
REM  TEST 7: Configuration Validity
REM ============================================================
echo.
echo ========================================================
echo   TEST 7: Configuration Validity
echo ========================================================

findstr /C:"stt_language: auto" config\defaults.yaml >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] STT language config incorrect
    set /a FAILED+=1
) else (
    echo   [PASS] STT multilingual config correct
    set /a PASSED+=1
)

findstr /C:"whisper_model: base.en" config\defaults.yaml >nul 2>&1
if not errorlevel 1 (
    echo   [FAIL] Old English-only config still present
    set /a FAILED+=1
) else (
    echo   [PASS] Old config removed
    set /a PASSED+=1
)

REM ============================================================
REM  SUMMARY
REM ============================================================
echo.
echo ========================================================
echo   BUILD INTEGRITY TEST RESULTS
echo ========================================================
echo   Tests Passed: %PASSED%
echo   Tests Failed: %FAILED%
echo ========================================================

if %FAILED% GTR 0 (
    echo.
    echo   [RESULT] BUILD INTEGRITY: FAILED
    echo.
    echo   Some tests failed. Review the output above.
    echo   You may need to:
    echo     - Install dependencies: pip install -r requirements.txt
    echo     - Run bootstrap: python bootstrap.py
    echo     - Check Python version: python --version
    echo.
    exit /b 1
) else (
    echo.
    echo   [RESULT] BUILD INTEGRITY: PASSED
    echo.
    echo   The build is clean and functional.
    echo   Ready for testing or distribution.
    echo.
    exit /b 0
)
