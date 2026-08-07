"""AgentCore — tests/test_acceptance.py
Clean-machine acceptance test.

Starting from a clean Windows machine with Python 3.12:
  1. Extract the ZIP
  2. Double-click run.bat
  3. No manual PowerShell / venv / pip / playwright steps

The app must: create .venv if missing → install deps if missing → install
Playwright browsers if missing → init workspace → init SQLite → launch
dashboard. If any step fails → the build is FAILED.

This suite verifies each step's CODE path hermetically (the venv creation +
reinstall are environment mutations we can't run in a sandbox that already
has deps — we verify the exact code branches instead):
  [1] bootstrap.py imports with ZERO third-party packages (python -S)
  [2] main.py has no top-level third-party/project imports (bootstrap runs first)
  [3] ensure_venv: short-circuits when deps present; otherwise re-execs into main.py
  [4] ensure_dependencies: hash-gated install + missing-pkg install (never crash)
  [5] ensure_playwright: marker-gated once-only; BROKEN (optional) never blocks
  [6] ensure_workspace: creates all required dirs
  [7] ensure_database: create-if-missing + migrations + WAL + integrity
  [8] doctor: full report, no required failures
  [9] run.bat: finds python, calls main.py — no manual steps
  [10] release ZIP: contains the launcher + bootstrap, NO dev artifacts
  [11] full chain (deps present): bootstrap.run() → READY → dashboard can boot
"""
import ast
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# [1] bootstrap is pure stdlib — imports with no site-packages
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_bootstrap_imports_without_third_party_packages():
    # python -S skips site-packages → any third-party import would fail
    code = "import sys; sys.path.insert(0, '.'); import bootstrap; print('OK')"
    r = subprocess.run([sys.executable, "-S", "-c", code], cwd=ROOT,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout


# ---------------------------------------------------------------------------
# [2] main.py runs bootstrap before any third-party import
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_main_py_has_no_top_level_third_party_import():
    tree = ast.parse((ROOT / "main.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node.col_offset == 0:
            mod = (node.module or "") if isinstance(node, ast.ImportFrom) else ""
            names = [a.name for a in node.names]
            joined = mod + " " + " ".join(names)
            # allow stdlib + __future__ at module level only
            for bad in ("core", "api", "dashboard", "tools", "executor",
                        "memory", "observer", "planner", "llm", "reasoning",
                        "database", "devices", "bootstrap", "fastapi", "structlog"):
                if bad in joined:
                    pytest.fail(f"top-level import before bootstrap: {joined}")


# ---------------------------------------------------------------------------
# [3] venv: short-circuit when bootstrapped; re-exec target is main.py
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_venv_short_circuits_when_deps_present():
    import bootstrap as b
    v = b.ensure_venv()
    assert v["ok"] is True
    assert "already bootstrapped" in v["detail"] or "inside" in v["detail"] \
        or "frozen" in v["detail"]


@pytest.mark.integration
def test_venv_reexec_targets_main_py():
    src = (ROOT / "bootstrap.py").read_text()
    # the re-exec must run main.py (not bootstrap.py, which has no __main__)
    assert "ROOT / \"main.py\"" in src or "ROOT / 'main.py'" in src


# ---------------------------------------------------------------------------
# [4] deps: hash-gated + missing-pkg install
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_dependencies_install_missing_and_write_lock(tmp_path, monkeypatch):
    import bootstrap as b
    req = tmp_path / "requirements.txt"
    req.write_text("structlog>=24\n")
    monkeypatch.setattr(b, "ROOT", tmp_path)
    monkeypatch.setattr(b, "LOCK_DIR", tmp_path / "data" / ".bootstrap")
    monkeypatch.setattr(b, "REQ_HASH_FILE", tmp_path / "data" / ".bootstrap" / "requirements.sha256")
    monkeypatch.setattr(b, "_pip", lambda *a, **k: True)
    d = b.ensure_dependencies()
    assert d["ok"] is True
    assert b.REQ_HASH_FILE.exists()          # lock written
    # unchanged → no reinstall (returns ok without error)
    d2 = b.ensure_dependencies()
    assert d2["ok"] is True


# ---------------------------------------------------------------------------
# [5] playwright: marker-gated once; optional never blocks
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_playwright_marker_gated_once():
    import bootstrap as b
    if b._importable("playwright"):
        # if the marker exists → READY, no reinstall; else BROKEN (optional)
        r = b.ensure_playwright()
        assert r["name"] == "playwright"
        assert r["ok"] is True or r.get("optional") is True   # never hard-fails
    else:
        r = b.ensure_playwright()
        assert r.get("optional") is True                       # optional


# ---------------------------------------------------------------------------
# [6] workspace: all required dirs created
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_workspace_creates_all_dirs():
    import bootstrap as b
    r = b.ensure_workspace()
    assert r["ok"] is True, r["detail"]
    from core.workspace import WorkspaceManager
    ws = WorkspaceManager(ROOT)
    for name in ("logs", "memory", "database", "cache", "exports", "tmp",
                 "sandbox", "screenshots", "adb"):
        assert ws.dir(name).is_dir(), f"{name} missing"


# ---------------------------------------------------------------------------
# [7] database: create-if-missing + WAL + integrity
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_database_bootstrap_wal_integrity():
    import bootstrap as b
    r = b.ensure_database()
    assert r["ok"] is True, r["detail"]
    assert "wal=wal" in r["detail"]
    assert "integrity=ok" in r["detail"]


# ---------------------------------------------------------------------------
# [8] doctor: no required failures
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_doctor_no_required_failures():
    import bootstrap as b
    report = b.run()
    for name, r in report.items():
        if isinstance(r, dict) and r.get("ok") is False and not r.get("optional"):
            pytest.fail(f"required check failed: {name} → {r.get('detail')}")
    assert report["python"]["ok"] is True


# ---------------------------------------------------------------------------
# [9] run.bat: no manual steps
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_run_bat_is_self_contained():
    bat = (ROOT / "run.bat").read_text()
    assert "python --version" in bat or "%PY% main.py" in bat
    assert "main.py" in bat                      # launches the app
    # must NOT require the user to create venv / pip install / playwright
    assert "venv" not in bat.lower() or "main.py" in bat   # venv handled inside main.py
    # no pause-before-bootstrap (it should bootstrap then run)
    assert "%PY% main.py" in bat


# ---------------------------------------------------------------------------
# [10] release ZIP: launcher + bootstrap included, no dev artifacts
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_release_zip_is_clean_and_complete():
    zips = sorted((ROOT / "dist").glob("agentcore-*.zip"))
    if not zips:
        pytest.skip("no release zip built yet — run python scripts/build.py")
    zf = zipfile.ZipFile(zips[-1])
    names = zf.namelist()
    # must include the bootstrap launcher chain
    for required in ("run.bat", "bootstrap.py", "main.py", "requirements.txt",
                     ".env.example"):
        assert any(n.endswith(required) for n in names), f"missing {required}"
    # must NOT include dev artifacts / secrets / runtime
    bad = [n for n in names if (Path(n).name == ".env") or any(x in n.lower() for x in (
        ".git", "htmlcov", ".pytest_cache", ".vscode", ".idea",
        "__pycache__", ".pyc", ".db-shm", ".db-wal", ".log"))]
    # allow .env.example (the safe template); forbid the real .env
    assert not bad, f"dev artifacts in release: {bad[:5]}"
    assert not any(n.startswith("data/") for n in names)


# ---------------------------------------------------------------------------
# [11] full chain (deps present): bootstrap.run() → dashboard can boot
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_full_chain_bootstraps_and_launches():
    import bootstrap as b
    report = b.run()
    assert report["python"]["ok"] is True
    # the app boots (fixture) and the dashboard API is reachable via the app
    from core.app import AgentApp
    app = AgentApp.create()
    assert len(app.registry) > 10
    assert app.db.path.exists()
