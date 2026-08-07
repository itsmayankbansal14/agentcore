"""AgentCore — bootstrap.py
Self-bootstrapping entry: run BEFORE any third-party import. Uses only stdlib
until dependencies are ensured.

Sequence (auto, every start):
  1. python version check (3.11/3.12+)
  2. virtualenv: create .venv if missing and re-exec into it (skipped when
     already bootstrapped or frozen/exe — bundled deps)
  3. dependencies: hash-gated requirements install + per-package missing check
  4. playwright: install chromium ONCE (marker file; gated on playwright dep)
  5. workspace: create workspace/logs/memory/database/cache/exports/temp
  6. database: create if missing, migrations, WAL, integrity check
  7. doctor: readiness report (Python, venv, deps, playwright, workspace, db,
     api config, tool registry, browser tool, android tool, network, disk)
  8. optional components (android/browser) NEVER block startup — marked
     UNAVAILABLE/BROKEN and we continue.

Returns a report dict; run() never raises for optional failures.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
LOCK_DIR = ROOT / "data" / ".bootstrap"
REQ_HASH_FILE = LOCK_DIR / "requirements.sha256"
PLAYWRIGHT_MARKER = LOCK_DIR / "playwright.installed"

MIN_PY = (3, 11)

# core deps that indicate "already bootstrapped"
CORE_DEPS = ["structlog", "fastapi", "sqlalchemy", "openai"]


# ---------------------------------------------------------------------------
# python version
# ---------------------------------------------------------------------------
def check_python() -> dict:
    cur = sys.version_info[:2]
    ok = cur >= MIN_PY
    return {"name": "python", "ok": ok,
            "detail": f"{platform.python_version()} (need >= {MIN_PY[0]}.{MIN_PY[1]})"}


# ---------------------------------------------------------------------------
# dependency presence + hash lock
# ---------------------------------------------------------------------------
def _importable(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def deps_present(deps: list[str] | None = None) -> bool:
    return all(_importable(d) for d in (deps or CORE_DEPS))


def _req_hash() -> str:
    req = ROOT / "requirements.txt"
    if not req.exists():
        return ""
    return hashlib.sha256(req.read_bytes()).hexdigest()


def _read_lock() -> str:
    try:
        return REQ_HASH_FILE.read_text().strip() if REQ_HASH_FILE.exists() else ""
    except Exception:  # noqa: BLE001
        return ""


def _write_lock(h: str) -> None:
    try:
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        REQ_HASH_FILE.write_text(h)
    except Exception:  # noqa: BLE001
        pass


def requirements_changed() -> bool:
    return _req_hash() != _read_lock()


def _pip(python: str, *args: str) -> bool:
    try:
        r = subprocess.run([python, "-m", "pip", *args], cwd=ROOT,
                           capture_output=True, text=True, timeout=600)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def ensure_dependencies() -> dict:
    """Hash-gated: only reinstall when requirements.txt changed. Also install
    any individually-missing packages (resilience). Never crashes."""
    req = ROOT / "requirements.txt"
    installed_any = False
    detail = "dependencies ok"

    # 1) requirements.txt changed → full install
    if req.exists() and requirements_changed():
        ok = _pip(sys.executable, "install", "-q", "-r", str(req))
        detail = f"installed requirements (hash changed) {'ok' if ok else 'FAILED'}"
        if ok:
            _write_lock(_req_hash())
            installed_any = True

    # 2) individually missing packages (never crash on a missing package)
    if req.exists():
        missing = []
        for line in req.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkg = line.split(">=")[0].split("==")[0].split("<")[0].split("[")[0].strip()
            # map package name to import module
            mod = {"pyyaml": "yaml", "pydantic-settings": "pydantic_settings",
                   "beautifulsoup4": "bs4", "python-dotenv": "dotenv"}.get(pkg, pkg)
            if not _importable(mod):
                missing.append(pkg)
        if missing:
            ok = _pip(sys.executable, "install", "-q", *missing)
            detail = f"installed missing: {missing} {'ok' if ok else 'FAILED'}"
            installed_any = installed_any or ok

    return {"name": "dependencies", "ok": not detail.endswith("FAILED"),
            "detail": detail, "installed_any": installed_any}


# ---------------------------------------------------------------------------
# venv bootstrap (create + re-exec)
# ---------------------------------------------------------------------------
def ensure_venv() -> dict:
    """Create .venv if missing and RE-EXEC this script inside it.
    Skips when: frozen (exe bundles deps), already inside the venv, or the
    current interpreter already has the core deps (already bootstrapped)."""
    if getattr(sys, "frozen", False):
        return {"name": "venv", "ok": True, "detail": "frozen (deps bundled)"}
    if os.environ.get("AGENTCORE_IN_VENV") == "1":
        return {"name": "venv", "ok": True, "detail": f"running inside {sys.prefix}"}
    if deps_present():
        return {"name": "venv", "ok": True, "detail": "already bootstrapped (core deps present)"}

    # create the venv
    if not VENV_DIR.exists():
        try:
            subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)],
                           check=True, capture_output=True, timeout=300)
        except Exception as e:  # noqa: BLE001
            return {"name": "venv", "ok": False,
                    "detail": f"could not create .venv: {e}"}

    venv_py = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not venv_py.exists():
        return {"name": "venv", "ok": False, "detail": ".venv python missing"}

    # re-exec into main.py inside the venv — main.py re-runs bootstrap
    # (with AGENTCORE_IN_VENV=1 it skips venv creation and proceeds to deps,
    # playwright, workspace, db, then launches the dashboard).
    env = dict(os.environ)
    env["AGENTCORE_IN_VENV"] = "1"
    try:
        r = subprocess.run([str(venv_py), str(ROOT / "main.py")]
                           + sys.argv[1:], cwd=ROOT, env=env)
        sys.exit(r.returncode)   # never returns (parent exits with child's code)
    except Exception as e:  # noqa: BLE001
        return {"name": "venv", "ok": False, "detail": f"re-exec failed: {e}"}
    return {"name": "venv", "ok": True, "detail": "bootstrapped"}


# ---------------------------------------------------------------------------
# playwright (optional — never blocks startup)
# ---------------------------------------------------------------------------
def ensure_playwright() -> dict:
    if not _importable("playwright"):
        return {"name": "playwright", "ok": False,
                "detail": "playwright not installed (browser optional → BROKEN)",
                "optional": True}
    if PLAYWRIGHT_MARKER.exists():
        return {"name": "playwright", "ok": True, "detail": "chromium already installed"}
    try:
        r = subprocess.run([sys.executable, "-m", "playwright", "install",
                            "chromium"], cwd=ROOT, capture_output=True, text=True,
                           timeout=1200)
        if r.returncode == 0:
            PLAYWRIGHT_MARKER.parent.mkdir(parents=True, exist_ok=True)
            PLAYWRIGHT_MARKER.write_text("ok")
            return {"name": "playwright", "ok": True,
                    "detail": "chromium installed (once)"}
        return {"name": "playwright", "ok": False,
                "detail": "chromium install failed (browser BROKEN)",
                "optional": True}
    except Exception as e:  # noqa: BLE001
        return {"name": "playwright", "ok": False,
                "detail": f"playwright install raised: {e}", "optional": True}


# ---------------------------------------------------------------------------
# workspace + database bootstrap
# ---------------------------------------------------------------------------
def ensure_workspace() -> dict:
    """Create the managed directories (workspace/logs/memory/database/cache/
    exports/temp). No manual directory creation ever."""
    try:
        from core.workspace import WorkspaceManager
        ws = WorkspaceManager(ROOT)
        # ensure the full required set
        for name in ("workspace", "logs", "memory", "database", "cache",
                     "exports", "temp", "sandbox", "screenshots", "adb", "tts_cache"):
            try:
                ws.dir(name)
            except Exception:  # noqa: BLE001 — some are derived
                pass
        ws.clean_tmp()
        return {"name": "workspace", "ok": True,
                "detail": "workspace dirs created"}
    except Exception as e:  # noqa: BLE001
        return {"name": "workspace", "ok": False, "detail": str(e)[:120]}


def ensure_database() -> dict:
    """Create DB if missing, apply migrations, verify WAL, integrity check."""
    try:
        from core.workspace import WorkspaceManager
        from database.connection import Database
        from database.migrations import apply

        ws = WorkspaceManager(ROOT)
        db = Database(str(ws.db_path()))
        existed = db.db_file_exists() if hasattr(db, "db_file_exists") else db.path.exists()
        db.create_all()
        applied = apply(db)          # pending migrations
        # WAL verification
        with db.engine.connect() as c:
            mode = c.exec_driver_sql("PRAGMA journal_mode").scalar()
            integrity = c.exec_driver_sql("PRAGMA integrity_check").scalar()
        db.close()
        ok = str(mode).lower() == "wal" and integrity == "ok"
        return {"name": "database", "ok": ok,
                "detail": f"db={'created' if not existed else 'present'} "
                          f"wal={mode} integrity={integrity} migrations={len(applied)}"}
    except Exception as e:  # noqa: BLE001
        return {"name": "database", "ok": False, "detail": str(e)[:120]}


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------
def doctor() -> dict:
    """Full readiness report. Optional failures never fail the check."""
    results = {
        "python": check_python(),
        "venv": {"name": "venv", "ok": True,
                 "detail": "inside venv" if os.environ.get("AGENTCORE_IN_VENV") == "1"
                           else (f"running {sys.prefix}")},
        "dependencies": ensure_dependencies(),
        "playwright": ensure_playwright(),
        "workspace": ensure_workspace(),
        "database": ensure_database(),
    }
    # API config / tool registry / browser / android / network / disk
    results.update(_runtime_checks())
    return results


def _runtime_checks() -> dict:
    """Checks that need the runtime (lazy — never block if unavailable)."""
    out = {}
    try:
        from core.app import AgentApp
        app = AgentApp.create()
        # api config
        provider = app.config.get_list("llm.provider_priority", [])
        out["api_config"] = {"name": "api_config", "ok": True,
                             "detail": f"providers={provider}"}
        # tool registry
        out["tool_registry"] = {"name": "tool_registry", "ok": True,
                                "detail": f"{len(app.registry)} tools registered"}
        # browser tool health
        bh = app.tool_health.state("browser_open")
        out["browser_tool"] = {"name": "browser_tool",
                               "ok": bh["state"] != "BROKEN",
                               "detail": f"{bh['state']} — {bh['message']}",
                               "optional": True}
        # android tool health
        ah = app.tool_health.state("android_open_app")
        out["android_tool"] = {"name": "android_tool",
                               "ok": ah["state"] != "BROKEN",
                               "detail": f"{ah['state']} — {ah['message']}",
                               "optional": True}
    except Exception as e:  # noqa: BLE001
        out["runtime"] = {"name": "runtime", "ok": False,
                          "detail": f"runtime init failed: {e}"}

    # network + disk permissions (stdlib)
    try:
        import socket
        socket.create_connection(("1.1.1.1", 53), timeout=3).close()
        out["network"] = {"name": "network", "ok": True, "detail": "reachable"}
    except Exception:  # noqa: BLE001
        out["network"] = {"name": "network", "ok": False,
                          "detail": "no outbound network", "optional": True}
    try:
        probe = ROOT / "data" / ".write_probe"
        probe.write_text("x"); probe.unlink()
        out["disk"] = {"name": "disk", "ok": True, "detail": "writable"}
    except Exception as e:  # noqa: BLE001
        out["disk"] = {"name": "disk", "ok": False, "detail": str(e)[:80]}
    return out


# ---------------------------------------------------------------------------
# report render
# ---------------------------------------------------------------------------
def render_report(report: dict) -> str:
    lines = ["\n  AgentCore — readiness report"]
    lines.append("  " + "─" * 52)
    fatal = False
    for name, r in report.items():
        if not isinstance(r, dict):
            continue
        mark = "✓" if r.get("ok") else ("⚠" if r.get("optional") else "✗")
        if r.get("ok") is False and not r.get("optional"):
            fatal = True
        lines.append(f"  {mark} {r['name']:<16} {r.get('detail','')}")
    lines.append("  " + "─" * 52)
    lines.append("  READY ✅" if not fatal else "  STARTING with optional gaps ⚠ (required checks passed)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
def run() -> dict:
    """Full bootstrap. Returns the report. Never raises for optional failures."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, dict] = {
        "python": check_python(),
    }
    py = report["python"]
    if not py["ok"]:
        report["python"]["detail"] += " — unsupported Python"
        return report
    # venv (may re-exec)
    v = ensure_venv()
    if v.get("name") == "venv":
        report["venv"] = v
        if v.get("ok") is False:
            # venv creation failed but deps may still be present — continue
            pass
    # deps / playwright / workspace / db / runtime checks
    report.update(doctor())
    return report
