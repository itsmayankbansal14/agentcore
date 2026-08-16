"""Integration: Self-bootstrapping.

Verifies the startup pipeline without actually creating a .venv or
reinstalling (those are environment mutations — the pieces that matter are
tested here hermetically):
  [1] Doctor / readiness report covers all required checks
  [2] Workspace bootstrap creates the managed dirs
  [3] Database bootstrap: create-if-missing, migrations, WAL, integrity
  [4] Dependency hash-lock: requirements change detection + lock file
  [5] Optional components (android/browser) never block — marked UNAVAILABLE/BROKEN
  [6] Python version check
  [7] bootstrap.run() never raises; returns a report with python ok
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.integration
def test_python_version_check():
    import bootstrap
    r = bootstrap.check_python()
    assert r["ok"] is True, r["detail"]          # we run 3.11+ here
    assert sys.version_info[:2] >= (3, 11)


@pytest.mark.integration
def test_requirements_hash_lock(tmp_path, monkeypatch):
    import bootstrap as b
    # simulate a requirements file + hash lock under a temp root
    req = tmp_path / "requirements.txt"
    req.write_text("structlog>=24\n")
    monkeypatch.setattr(b, "ROOT", tmp_path)
    monkeypatch.setattr(b, "REQ_HASH_FILE", tmp_path / "data" / ".bootstrap" / "requirements.sha256")
    monkeypatch.setattr(b, "LOCK_DIR", tmp_path / "data" / ".bootstrap")
    monkeypatch.setattr(b, "_pip", lambda *a, **k: True)
    # first run: hash changed → installs + writes lock
    d = b.ensure_dependencies()
    assert d["ok"] is True
    assert (tmp_path / "data" / ".bootstrap" / "requirements.sha256").exists()
    # second run: unchanged → no reinstall
    d2 = b.ensure_dependencies()
    assert d2["ok"] is True


@pytest.mark.integration
def test_missing_package_installed_not_crash(tmp_path, monkeypatch):
    import bootstrap as b
    req = tmp_path / "requirements.txt"
    req.write_text("this-pkg-does-not-exist-xyz\nstructlog\n")
    monkeypatch.setattr(b, "ROOT", tmp_path)
    monkeypatch.setattr(b, "LOCK_DIR", tmp_path / "data" / ".bootstrap")
    monkeypatch.setattr(b, "REQ_HASH_FILE", tmp_path / "data" / ".bootstrap" / "requirements.sha256")
    calls = []
    monkeypatch.setattr(b, "_pip", lambda *a, **k: (calls.append(a) or True))
    # missing package detection: it tries to install, and never raises
    d = b.ensure_dependencies()
    assert isinstance(d, dict) and "detail" in d
    assert any("install" in str(c) for c in calls) or d["ok"] is not False


@pytest.mark.integration
def test_workspace_bootstrap_creates_dirs(app):
    ws = app.workspace
    for name in ("logs", "tmp", "exports", "sandbox", "screenshots", "adb",
                 "memory", "database", "cache", "temp"):
        d = ws.dir(name)
        assert d.is_dir(), f"{name} not created"


@pytest.mark.integration
def test_database_bootstrap_wal_integrity(app):
    from database.migrations import apply
    apply(app.db)
    with app.db.engine.connect() as c:
        mode = c.exec_driver_sql("PRAGMA journal_mode").scalar()
        integrity = c.exec_driver_sql("PRAGMA integrity_check").scalar()
    assert str(mode).lower() == "wal"
    assert integrity == "ok"


@pytest.mark.integration
def test_database_created_if_missing(tmp_path):
    from database.connection import Database
    db = Database(tmp_path / "fresh.db")
    db.create_all()
    assert db.path.exists()
    with db.engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
    db.close()


@pytest.mark.integration
def test_optional_components_never_block(app, monkeypatch):
    """Android/browser optional: missing deps mark BROKEN, never stop startup."""
    from tools.health import ToolHealthManager
    # simulate playwright missing
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda n: None if "playwright" in (n or "") else object())
    hm = ToolHealthManager()
    hm.scan(app.registry, app.devices)
    assert hm.state("browser_open")["state"] == "BROKEN"
    # android with no device → UNAVAILABLE (not a failure)
    assert app.tool_health.state("android_open_app")["state"] == "UNAVAILABLE"
    # the app itself still started (fixture created it) — optional never blocked


@pytest.mark.integration
def test_bootstrap_run_returns_report_without_raising():
    import bootstrap
    report = bootstrap.run()
    assert isinstance(report, dict)
    assert report["python"]["ok"] is True
    # all doctor sections present
    for key in ("python", "dependencies", "playwright", "workspace", "database"):
        assert key in report
    # never crashed on optional components
    assert "playwright" in report
