"""AgentCore — tests/test_bootstrap_rules.py
Bootstrap environment rules (hermetic — monkeypatched, never really re-execs):

  1. frozen                          → bundled runtime (continue)
  2. interpreter inside .venv        → continue
  3. global Python WITH deps         → NOT bootstrapped; create .venv + re-exec
  4. no .venv (global python)        → create .venv + re-exec into main.py
  5. wrong Python version (3.10/3.13)→ REJECTED with a clear detail
  6. correct Python version (3.11/3.12) → accepted

The re-exec target must always be main.py (bootstrap.py has no __main__).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import bootstrap as b

ROOT = Path(__file__).resolve().parent.parent


class _FakeRun:
    """Captures the re-exec subprocess call instead of running it."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.returncode = 0

    def __call__(self, cmd, cwd=None, env=None, **kwargs):
        self.calls.append((cmd, env))
        return type("R", (), {"returncode": self.returncode})()


# ---------------------------------------------------------------------------
# 1) frozen → bundled runtime
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_frozen_uses_bundled_runtime(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    v = b.ensure_venv()
    assert v["ok"] is True and "frozen" in v["detail"]


# ---------------------------------------------------------------------------
# 2) inside AgentCore/.venv → continue (env marker OR sys.prefix)
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_inside_venv_via_env_marker_continues(monkeypatch):
    monkeypatch.delenv("AGENTCORE_IN_VENV", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("AGENTCORE_IN_VENV", "1")
    v = b.ensure_venv()
    assert v["ok"] is True and "inside" in v["detail"]


@pytest.mark.unit
def test_inside_venv_via_sys_prefix_continues(monkeypatch):
    monkeypatch.delenv("AGENTCORE_IN_VENV", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    venv = b.VENV_DIR.resolve()
    monkeypatch.setattr(sys, "prefix", str(venv / "bin"), raising=False)
    v = b.ensure_venv()
    assert v["ok"] is True and "inside" in v["detail"]


# ---------------------------------------------------------------------------
# 3) global Python WITH dependencies installed → still NOT bootstrapped
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_global_python_with_deps_is_not_bootstrapped(monkeypatch, tmp_path):
    """The core bug being fixed: a global interpreter that happens to have
    the packages installed must NOT be treated as already bootstrapped."""
    monkeypatch.delenv("AGENTCORE_IN_VENV", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    # global python prefix (NOT under .venv)
    monkeypatch.setattr(sys, "prefix", "/usr/local", raising=False)
    # pretend the core deps are importable in this global python
    monkeypatch.setattr(b, "deps_present", lambda deps=None: True)
    monkeypatch.setattr(b.sys, "exit", lambda code=None: None)
    fake = _FakeRun()
    monkeypatch.setattr(b.subprocess, "run", fake)
    # .venv already exists (a previous run) → no create call, straight re-exec
    venv_dir = tmp_path / ".venv"
    (venv_dir / "bin").mkdir(parents=True, exist_ok=True)
    (venv_dir / "bin" / "python").write_text("")
    monkeypatch.setattr(b, "VENV_DIR", venv_dir)
    v = b.ensure_venv()
    assert v["ok"] is True
    # it MUST have re-exec'd into the venv python, not continued
    assert fake.calls and "main.py" in fake.calls[0][0][1]


# ---------------------------------------------------------------------------
# 4) no .venv (global python) → create + re-exec into main.py
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_no_venv_creates_then_reexecs_main_py(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTCORE_IN_VENV", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "prefix", "/usr/local", raising=False)
    monkeypatch.setattr(b.sys, "exit", lambda code=None: None)
    venv_dir = tmp_path / ".venv"      # deliberately NOT created yet
    monkeypatch.setattr(b, "VENV_DIR", venv_dir)
    monkeypatch.setattr(b, "ROOT", tmp_path)
    created: list[list[str]] = []
    reexec: list[list[str]] = []

    def _run(cmd, cwd=None, env=None, **kwargs):
        if "-m" in cmd and "venv" in cmd:
            created.append(cmd)
            # the real `python -m venv` would create bin/python — simulate it
            (venv_dir / "bin").mkdir(parents=True, exist_ok=True)
            (venv_dir / "bin" / "python").write_text("")
            return type("R", (), {"returncode": 0})()
        reexec.append((cmd, env))
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(b.subprocess, "run", _run)
    v = b.ensure_venv()
    assert created, "venv creation must be attempted when .venv is missing"
    # then re-exec into the venv python running main.py (with env)
    assert reexec and str(venv_dir / "bin" / "python") in reexec[0][0][0]
    assert str(tmp_path / "main.py") in reexec[0][0][1]
    assert reexec[0][1] and reexec[0][1].get("AGENTCORE_IN_VENV") == "1"


# ---------------------------------------------------------------------------
# 5) python version range: reject 3.10 / 3.13, accept 3.11 / 3.12
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.parametrize("major,minor,expected", [
    (3, 9, False), (3, 10, False), (3, 11, True), (3, 12, True),
    (3, 13, False), (3, 14, False), (4, 0, False),
])
def test_python_version_range(monkeypatch, major, minor, expected):
    monkeypatch.setattr(sys, "version_info", (major, minor, 0, "final", 0))
    r = b.check_python()
    assert r["ok"] is expected
    if major == 3 and minor >= 13:
        assert "3.13+" in r["detail"] or "not supported" in r["detail"]
    if expected:
        assert "3.11" in r["detail"] and "3.13" in r["detail"]


# ---------------------------------------------------------------------------
# helpers stay consistent
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_inside_project_venv_detects_prefix(monkeypatch):
    venv = b.VENV_DIR.resolve()
    monkeypatch.delenv("AGENTCORE_IN_VENV", raising=False)
    monkeypatch.setattr(sys, "prefix", str(venv), raising=False)
    assert b._inside_project_venv() is True
    monkeypatch.setattr(sys, "prefix", "/usr/local", raising=False)
    assert b._inside_project_venv() is False


@pytest.mark.unit
def test_run_rejects_unsupported_python_before_venv(monkeypatch):
    monkeypatch.setattr(sys, "version_info", (3, 13, 0, "final", 0))
    report = b.run()
    assert report["python"]["ok"] is False
    assert "unsupported Python" in report["python"]["detail"]
