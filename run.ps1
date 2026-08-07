# ============================================================
# AgentCore - one-command launcher (Windows PowerShell)
# Bootstraps everything (.venv, deps, playwright, workspace,
# database) via main.py, then starts the dev console.
# Only manual prerequisite: Python 3.11/3.12 installed.
# ============================================================
Set-Location $PSScriptRoot

# locate python
$py = $null
foreach ($cand in @("python", "py -3")) {
    try {
        $v = & $cand --version 2>$null
        if ($LASTEXITCODE -eq 0) { $py = $cand; break }
    } catch {}
}
if (-not $py) {
    Write-Host "[ERROR] Python 3.11+ not found. Install from https://www.python.org/downloads/" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "AgentCore - bootstrapping (venv, deps, playwright, workspace, database)..." -ForegroundColor Cyan
& $py main.py
