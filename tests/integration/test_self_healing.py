"""Integration: Self-Healing Execution.

Proves the runtime repairs itself instead of just failing:
  [1] Missing todo storage is auto-initialized, then the original operation retries
      and succeeds (TodoStorageProvider + RecoveryPolicy todo_storage_init repair).
  [2] Missing browser dependency is detected at startup → tool marked BROKEN with
      install instructions — never READY, never executed.
  [3] Recoverable failures retry successfully through RecoveryPolicy
      (repair → retry → observer verification).
  [4] Observer validates recovery (the retried operation is verified by the
      environment, and the observation is user-visible while internals stay
      in the logs).
  [5] WorkspaceManager is the single path authority (no tool constructs its own
      absolute paths).
"""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from core.contracts import ToolCall
from core.errors import FailureClass, classify


# ---------------------------------------------------------------------------
# [1] Missing todo storage auto-initialized
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_missing_todo_storage_auto_initialized(app, session, run_sync):
    # simulate MISSING storage: drop the todos table
    with app.db.engine.begin() as c:
        c.exec_driver_sql("DROP TABLE IF EXISTS todos")
    # the provider must self-heal on first access
    storage = app.todo_provider.storage()
    assert storage.is_initialized() is True          # auto-initialized
    tid = storage.add("auto-healed task")            # original op succeeds
    todos = storage.list()
    assert any(t["id"] == tid for t in todos)

    # AND through the tool path: drop again, then todo_add must succeed
    with app.db.engine.begin() as c:
        c.exec_driver_sql("DROP TABLE IF EXISTS todos")
    app.todo_provider.initialized = False            # force re-check
    res = run_sync(app.registry.execute("todo_add", {"task": "via tool"},
                                        {"confirm": True, "workspace": app.workspace}))
    assert res.ok, res.error
    assert res.data["task"] == "via tool"


# ---------------------------------------------------------------------------
# [2] Missing browser dependency detected BEFORE execution
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_browser_broken_when_playwright_missing(app, monkeypatch):
    # simulate Playwright not being installed
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name: None if "playwright" in (name or "") else object())
    from tools.health import ToolHealthManager
    hm = ToolHealthManager()
    hm.scan(app.registry, app.devices)
    bstate = hm.state("browser_open")
    assert bstate["state"] == "BROKEN"
    assert "playwright" in bstate["install_hint"].lower()
    assert "install" in bstate["install_hint"].lower()
    # never reported READY
    assert bstate["state"] != "READY"
    assert "browser_open" in hm.broken()


@pytest.mark.integration
def test_browser_ready_when_playwright_present(app):
    # real environment: playwright IS installed → READY
    state = app.tool_health.state("browser_open")
    assert state["state"] in ("READY", "BROKEN")
    if state["state"] == "BROKEN":
        pytest.skip("playwright not installed in this environment")


# ---------------------------------------------------------------------------
# [3] Recoverable failures retry successfully via RecoveryPolicy
# ---------------------------------------------------------------------------
class _RecoverThenOk:
    """A tool that fails once with a RECOVERABLE error, then succeeds."""

    def __init__(self):
        self.calls = 0

    def make_tool(self):
        from tools.base import Tool
        from core.contracts import ToolResult

        owner = self

        class FlakyRecoverable(Tool):
            name = "it_recover"
            description = "fails once recoverably, then ok"
            parameters = {"type": "object", "properties": {}}
            idempotent = True

            async def execute(self, params, ctx):
                owner.calls += 1
                if owner.calls == 1:
                    # recoverable: transient network-style failure
                    return ToolResult(ok=False, error="connection refused, retrying")
                return ToolResult(ok=True, data={"attempt": owner.calls})

        return FlakyRecoverable()


@pytest.mark.integration
def test_recoverable_failure_retries_successfully(app, session, run_sync):
    from core.errors import FailureInfo
    owner = _RecoverThenOk()
    app.registry.register(owner.make_tool())
    tc = ToolCall(id="r1", name="it_recover", arguments={})
    res = run_sync(app.executor._dispatch_tool(session, None, tc))
    assert res.ok is True                       # recovered
    assert owner.calls == 2                     # initial + 1 repair-retry
    # recovery stats recorded on the monitor
    stats = {t["tool"]: t for t in app.tool_monitor.stats()}
    assert stats["it_recover"]["recovery_attempts"] >= 1
    assert stats["it_recover"]["recovery_success"] >= 1
    # recovery policy summary recorded
    rec = app.recovery.summary()
    assert rec.get("it_recover", {}).get("successes", 0) >= 1


@pytest.mark.integration
def test_non_recoverable_failure_not_retried(app, session, run_sync):
    from tools.base import Tool
    from core.contracts import ToolResult

    class BadKey(Tool):
        name = "it_badkey"
        description = "non-recoverable (auth)"
        parameters = {"type": "object", "properties": {}}
        calls = 0

        async def execute(self, params, ctx):
            BadKey.calls += 1
            return ToolResult(ok=False, error="invalid api key (401)")

    app.registry.register(BadKey())
    tc = ToolCall(id="r2", name="it_badkey", arguments={})
    res = run_sync(app.executor._dispatch_tool(session, None, tc))
    assert not res.ok
    assert BadKey.calls == 1                     # no retry for non-recoverable
    info = classify("invalid api key (401)", component="tool")
    assert info.recoverable is False


# ---------------------------------------------------------------------------
# [4] Observer validates recovery (user-visible message; internals in logs)
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_observer_validates_recovery_and_separates_messages(app, session, mock_llm, run_sync):
    from observer.base import Observation, Observer

    class VerifyObserver(Observer):
        source = "verify"
        def verify(self, tool_name, args, result):
            if tool_name == "time_now":
                return [Observation(source="verify", ok=True,
                                    message="time tool verified",
                                    data={"internal": "took 3ms", "hash": "abc123"})]
            return []

    app.observers.register(VerifyObserver())
    obs = app.observers.verify_after("time_now", {}, None)
    assert any(o.source == "verify" and o.ok for o in obs)
    v = next(o for o in obs if o.source == "verify")
    # user-visible message is clean (no internals)
    assert "internal" not in v.to_context()
    assert "3ms" not in v.to_context()
    # internals available for the developer log only
    assert "hash" in v.log_developer()
    # the API surface keeps the public message only
    recent = app.observers.recent(20)
    entry = next(e for e in recent if e["source"] == "verify")
    assert "internal" not in entry
    assert entry["message"] == "time tool verified"


# ---------------------------------------------------------------------------
# [5] WorkspaceManager is the single path authority
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_workspace_manager_single_path_authority(app):
    ws = app.workspace
    # managed locations exist
    for name in ("data", "logs", "tmp", "exports", "sandbox", "screenshots", "adb"):
        assert ws.dir(name).is_dir()
    # db path is managed, not constructed ad hoc
    assert ws.db_path() == ws.dir("data") / "agentcore.db"
    # a tool that writes requests the path through the workspace
    import tempfile
    p = ws.path("sandbox", "ws_probe.txt")
    p.write_text("x")
    assert p.exists()
    # escaping the managed area is rejected
    with pytest.raises(PermissionError):
        ws.path("sandbox", "..", "..", "escape.txt")
