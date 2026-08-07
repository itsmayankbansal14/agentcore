@echo off
REM ============================================================
REM  AgentCore - Windows build pipeline (hard gates)
REM
REM  VERIFY → INSTALL DEPS → RE-VERIFY → TESTS → PYINSTALLER --clean
REM          → SMOKE TEST EXE → PACKAGE
REM
REM  The build EXITS IMMEDIATELY if verification fails.
REM  PyInstaller is only invoked after all checks pass.
REM ============================================================
setlocal enabledelayedexpansion
title AgentCore Build
cd /d "%~dp0"

echo.
echo  ============================================
echo    AGENTCORE BUILD  -  Verify ^> Build ^> Test ^> Package
echo  ============================================
echo.

REM ---------- Python present? ----------
python --version >nul 2>nul
if errorlevel 1 (
    echo [ABORT] Python not found. Install from https://www.python.org/downloads/
    echo         IMPORTANT: tick "Add Python to PATH".
    pause
    exit /b 1
)

REM ============ STEP 1/7: VERIFY (mandatory) ============
echo.
echo === [1/7] VERIFY build prerequisites ===
python scripts\verify_build.py
if errorlevel 1 (
    echo.
    echo [ABORT] Verification FAILED. Fix the issues above, then re-run.
    exit /b 1
)

REM ============ STEP 2/7: INSTALL DEPENDENCIES ============
echo.
echo === [2/7] Install dependencies (pip install -r requirements.txt) ===
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ABORT] Dependency installation FAILED. See pip error above.
    exit /b 1
)

REM ============ STEP 3/7: RE-VERIFY ============
echo.
echo === [3/7] Re-verify after install ===
python scripts\verify_build.py
if errorlevel 1 (
    echo.
    echo [ABORT] Packages still missing after install. See above. Build will NOT continue.
    exit /b 1
)

REM ============ STEP 4/7: TESTS ============
echo.
echo === [4/7] Run test suites ===
python tests\test_architecture.py || ( echo [ABORT] Architecture tests failed & exit /b 1 )
python tests\smoke.py || ( echo [ABORT] Core tests failed & exit /b 1 )
python tests\test_api.py || ( echo [ABORT] API tests failed & exit /b 1 )

REM ============ STEP 5/7: PYINSTALLER --clean ============
echo.
echo === [5/7] PyInstaller --clean (all verification passed) ===
python -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo [setup] Installing PyInstaller...
    python -m pip install pyinstaller || ( echo [ABORT] PyInstaller install failed & exit /b 1 )
)
python -m PyInstaller ^
    --clean --noconfirm --onefile --console ^
    --name AgentCore ^
    --distpath dist ^
    --workpath build ^
    --specpath build ^
    --add-data "ui;ui" ^
    --add-data "config;config" ^
    --hidden-import sqlalchemy ^
    --hidden-import structlog ^
    --hidden-import pydantic ^
    --hidden-import fastapi ^
    --hidden-import uvicorn ^
    --hidden-import websockets ^
    --hidden-import numpy ^
    --hidden-import pypdf ^
    --hidden-import starlette ^
    main.py
if errorlevel 1 (
    echo [ABORT] PyInstaller failed.
    exit /b 1
)

REM ============ STEP 6/7: SMOKE TEST EXE ============
echo.
echo === [6/7] Smoke test the built executable ===
if not exist "dist\AgentCore.exe" (
    echo [ABORT] dist\AgentCore.exe not found.
    exit /b 1
)
dist\AgentCore.exe --selfcheck
if errorlevel 1 (
    echo.
    echo [ABORT] Executable smoke test FAILED.
    exit /b 1
)

REM ============ STEP 7/7: PACKAGE ============
echo.
echo === [7/7] Package build ===
python scripts\build.py --only package
if errorlevel 1 (
    echo [ABORT] Packaging failed.
    exit /b 1
)

echo.
echo  ============================================
echo    BUILD COMPLETE.
echo    - Executable : dist\AgentCore.exe
echo    - Package    : dist\agentcore-*.zip
echo    Keep your .env NEXT TO the exe (not bundled).
echo  ============================================
pause
