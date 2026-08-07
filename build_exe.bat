@echo off
REM ============================================================
REM  AgentCore - Build a Windows .exe (one-file app)
REM  This now runs the full gated pipeline: Verify → Install →
REM  Re-verify → Tests → PyInstaller --clean → Smoke exe → Package.
REM  Just double-click; it delegates to build.bat.
REM ============================================================
call build.bat
