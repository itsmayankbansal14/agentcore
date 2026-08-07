# AgentCore — Windows Installer (preparation)

Target: **AgentCoreInstaller.exe** (Inno Setup script included).

## Current status: PREPARED (not built here)

The `.iss` script is ready. Building the actual installer requires **Windows**
with **Inno Setup 6** (free) — this sandbox is Linux and can't run ISCC.

## To build (on Windows)

1. Install Inno Setup 6: https://jrsoftware.org/isdl.php
2. Build the exe first (so `dist/AgentCore.exe` exists):
   ```
   build.bat        # or: python scripts/build.py
   ```
3. Compile the installer:
   ```
   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\AgentCoreInstaller.iss
   ```
4. Output: `dist\AgentCoreInstaller.exe`

## What the installer does

- Installs the runtime + launcher to `%LocalAppData%\Programs\AgentCore`
- Creates **Start Menu** + optional **Desktop** shortcuts to `AgentCore.exe`
- Registers an **uninstall entry** (Control Panel → Uninstall)
- **First launch runs bootstrap automatically**: creates `.venv`, installs
  deps, installs Playwright chromium, creates workspace, initializes SQLite,
  then starts the dev console — the end user never reads docs
- Per-user install (`PrivilegesRequired=lowest`) — no admin needed

## Release quality

`python scripts/build.py` now enforces a **release-quality gate**: the package
fails if it contains `.env` (real), `.git`, `.github`, `.gitignore`, `.coverage`,
`.pytest_cache`, `htmlcov`, `.vscode`, `.idea`, `__pycache__`, `*.pyc`,
`*.db-shm`, `*.db-wal`, `*.log`, or caches.
