@echo off
REM ============================================================
REM  AgentCore Quick Start — Run This First
REM  Date: 2026-09-17
REM ============================================================
title AgentCore Quick Start
cd /d "%~dp0"

echo.
echo ============================================================
echo   AGENTCORE QUICK START
echo   Time: %TIME%
echo ============================================================
echo.
echo This will:
echo   1. Validate your environment
echo   2. Bootstrap dependencies if needed
echo   3. Launch the first voice test
echo.
echo Press any key to continue, or Ctrl+C to abort...
pause >nul

REM ============================================================
REM  STEP 1: Environment Validation
REM ============================================================
echo.
echo ========================================
echo   STEP 1: Validating Environment
echo ========================================
call validate_env.bat
if errorlevel 1 (
    echo.
    echo [ERROR] Environment validation failed.
    echo         Run validate_env.bat again to see details.
    echo.
    pause
    exit /b 1
)

REM ============================================================
REM  STEP 2: Bootstrap (if needed)
REM ============================================================
echo.
echo ========================================
echo   STEP 2: Running Bootstrap
echo ========================================
python bootstrap.py
if errorlevel 1 (
    echo.
    echo [ERROR] Bootstrap failed.
    echo         Check errors above and try again.
    echo.
    pause
    exit /b 1
)

REM ============================================================
REM  STEP 3: Doctor Check
REM ============================================================
echo.
echo ========================================
echo   STEP 3: Health Check (Doctor)
echo ========================================
python main.py doctor
if errorlevel 1 (
    echo.
    echo [WARN] Doctor reported issues.
    echo        You can still try voice testing.
    echo.
    pause
)

REM ============================================================
REM  STEP 4: Voice Test Instructions
REM ============================================================
echo.
echo ========================================
echo   READY FOR VOICE TEST
echo ========================================
echo.
echo The environment is ready. Now let's test voice interaction.
echo.
echo IMPORTANT:
echo   - Make sure your microphone is connected
echo   - Make sure your speakers/headphones are connected
echo   - Find a quiet room
echo   - Speak clearly
echo.
echo When you're ready, I'll launch the voice runtime.
echo.
echo Press any key to launch voice test...
pause >nul

echo.
echo ========================================
echo   LAUNCHING VOICE RUNTIME
echo ========================================
echo.
echo The voice runtime will start in persistent loop mode.
echo.
echo WHAT TO DO:
echo   1. Wait for: "🎤 listening... (speak now)"
echo   2. Speak clearly: "What time is it?"
echo   3. Wait for agent to respond
echo   4. Try second interaction: "Hello"
echo   5. Press Ctrl+C to stop when done
echo.
echo If you see errors, check VALIDATION.md for troubleshooting.
echo.
echo Starting in 3 seconds...
timeout /t 3 /nobreak >nul

REM Launch voice runtime
python main.py voice --loop

echo.
echo ========================================
echo   VOICE SESSION ENDED
echo ========================================
echo.
echo If the voice test worked:
echo   ✓ Your microphone captured audio
echo   ✓ STT transcribed your speech
echo   ✓ Agent responded correctly
echo   ✓ TTS played audio
echo   ✓ Loop continued for second interaction
echo.
echo Next steps:
echo   - If it worked: Try "Open YouTube" to test browser automation
echo   - If it failed: See VALIDATION.md for troubleshooting
echo   - To test again: Run this script again
echo.
pause
