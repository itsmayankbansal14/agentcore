@echo off
REM ============================================================
REM  AgentCore Build Cleanup Script
REM  Removes unnecessary files, caches, and build artifacts
REM  Date: 2026-09-17
REM ============================================================
setlocal enabledelayedexpansion
title AgentCore Build Cleanup
cd /d "%~dp0"

echo.
echo ========================================================
echo   AGENTCORE BUILD CLEANUP
echo   Time: %TIME%
echo ========================================================
echo.
echo This will remove:
echo   - Python cache files (__pycache__, *.pyc)
echo   - Build artifacts (dist/, build/, *.spec)
echo   - Test caches (.pytest_cache/)
echo   - IDE artifacts (.vscode/, .idea/)
echo   - OS files (.DS_Store, Thumbs.db)
echo   - Log files (logs/)
echo   - Runtime data (data/)
echo   - Virtual environment (.venv/)
echo.
echo Essential files will be preserved:
echo   - Source code (*.py)
echo   - Configuration (config/)
echo   - Documentation (*.md)
echo   - Requirements (requirements.txt)
echo   - Scripts (*.bat)
echo.
set /p CONFIRM="Continue with cleanup? (y/N): "
if /i not "%CONFIRM%"=="y" (
    echo Cleanup cancelled.
    pause
    exit /b 0
)

echo.
echo ========================================================
echo   STARTING CLEANUP
echo ========================================================

set "REMOVED=0"
set "ERRORS=0"

REM ============================================================
REM  Python Cache Files
REM ============================================================
echo.
echo [1/9] Removing Python cache files...
for /r %%d in (__pycache__) do (
    if exist "%%d" (
        rmdir /s /q "%%d" 2>nul
        if not exist "%%d" (
            echo   Removed: %%d
            set /a REMOVED+=1
        ) else (
            echo   [ERROR] Could not remove: %%d
            set /a ERRORS+=1
        )
    )
)

for /r %%f in (*.pyc *.pyo) do (
    if exist "%%f" (
        del /q "%%f" 2>nul
        if not exist "%%f" (
            set /a REMOVED+=1
        ) else (
            set /a ERRORS+=1
        )
    )
)

REM ============================================================
REM  Build Artifacts
REM ============================================================
echo.
echo [2/9] Removing build artifacts...
if exist "dist\" (
    rmdir /s /q "dist" 2>nul
    if not exist "dist\" (
        echo   Removed: dist/
        set /a REMOVED+=1
    ) else (
        echo   [ERROR] Could not remove: dist/
        set /a ERRORS+=1
    )
)

if exist "build\" (
    rmdir /s /q "build" 2>nul
    if not exist "build\" (
        echo   Removed: build/
        set /a REMOVED+=1
    ) else (
        echo   [ERROR] Could not remove: build/
        set /a ERRORS+=1
    )
)

for %%f in (*.spec) do (
    if exist "%%f" (
        del /q "%%f" 2>nul
        if not exist "%%f" (
            echo   Removed: %%f
            set /a REMOVED+=1
        )
    )
)

REM ============================================================
REM  Test Caches
REM ============================================================
echo.
echo [3/9] Removing test caches...
if exist ".pytest_cache\" (
    rmdir /s /q ".pytest_cache" 2>nul
    if not exist ".pytest_cache\" (
        echo   Removed: .pytest_cache/
        set /a REMOVED+=1
    )
)

if exist ".coverage" (
    del /q ".coverage" 2>nul
    if not exist ".coverage" (
        echo   Removed: .coverage
        set /a REMOVED+=1
    )
)

if exist "htmlcov\" (
    rmdir /s /q "htmlcov" 2>nul
    if not exist "htmlcov\" (
        echo   Removed: htmlcov/
        set /a REMOVED+=1
    )
)

REM ============================================================
REM  IDE Artifacts
REM ============================================================
echo.
echo [4/9] Removing IDE artifacts...
if exist ".vscode\" (
    rmdir /s /q ".vscode" 2>nul
    if not exist ".vscode\" (
        echo   Removed: .vscode/
        set /a REMOVED+=1
    )
)

if exist ".idea\" (
    rmdir /s /q ".idea" 2>nul
    if not exist ".idea\" (
        echo   Removed: .idea/
        set /a REMOVED+=1
    )
)

REM ============================================================
REM  OS Files
REM ============================================================
echo.
echo [5/9] Removing OS files...
for /r %%f in (.DS_Store Thumbs.db desktop.ini) do (
    if exist "%%f" (
        del /q "%%f" 2>nul
        if not exist "%%f" (
            set /a REMOVED+=1
        )
    )
)

REM ============================================================
REM  Log Files
REM ============================================================
echo.
echo [6/9] Removing log files...
if exist "logs\" (
    rmdir /s /q "logs" 2>nul
    if not exist "logs\" (
        echo   Removed: logs/
        set /a REMOVED+=1
    )
)

REM ============================================================
REM  Runtime Data
REM ============================================================
echo.
echo [7/9] Removing runtime data...
if exist "data\" (
    echo   [INFO] Removing data/ (runtime files, databases, screenshots)
    rmdir /s /q "data" 2>nul
    if not exist "data\" (
        echo   Removed: data/
        set /a REMOVED+=1
    ) else (
        echo   [WARN] data/ could not be fully removed (may be in use)
        set /a ERRORS+=1
    )
)

REM ============================================================
REM  Virtual Environment (OPTIONAL)
REM ============================================================
echo.
echo [8/9] Virtual environment cleanup (optional)...
if exist ".venv\" (
    echo   [INFO] .venv/ exists (contains installed packages)
    set /p REMOVE_VENV="Remove .venv/? You'll need to re-run bootstrap. (y/N): "
    if /i "!REMOVE_VENV!"=="y" (
        rmdir /s /q ".venv" 2>nul
        if not exist ".venv\" (
            echo   Removed: .venv/
            set /a REMOVED+=1
        ) else (
            echo   [ERROR] Could not remove .venv/ (may be in use)
            set /a ERRORS+=1
        )
    ) else (
        echo   Skipped: .venv/
    )
) else (
    echo   Not found: .venv/
)

REM ============================================================
REM  Temporary Files
REM ============================================================
echo.
echo [9/9] Removing temporary files...
for /r %%f in (*.tmp *.temp *.bak *~) do (
    if exist "%%f" (
        del /q "%%f" 2>nul
        if not exist "%%f" (
            set /a REMOVED+=1
        )
    )
)

REM ============================================================
REM  Summary
REM ============================================================
echo.
echo ========================================================
echo   CLEANUP COMPLETE
echo ========================================================
echo   Items removed: %REMOVED%
echo   Errors: %ERRORS%
echo ========================================================

if %ERRORS% GTR 0 (
    echo.
    echo   [WARN] Some files could not be removed.
    echo          They may be in use or require admin rights.
    echo.
) else (
    echo.
    echo   [SUCCESS] Build cleaned successfully.
    echo.
)

echo Next steps:
echo   1. Run 'python bootstrap.py' to verify integrity
echo   2. Run 'python main.py doctor' to check health
echo   3. Test voice: 'python main.py voice --loop'
echo.
pause
