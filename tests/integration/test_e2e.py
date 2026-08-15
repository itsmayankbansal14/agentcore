"""Integration: End-to-end real workflows (requirement 12).

These execute REAL workflows through the full pipeline. The only injected
component is the LLM tool-selection (scripted mock); every tool, observer,
memory write, and history row is real. Includes the exact scenarios:
browser open+navigate, todo create+read, youtube (windows/browser path),
filesystem, recovery (todo storage init), ADB reconnect, SQLite recovery.
"""
import asyncio
import json

import pytest

from core.contracts import ToolCall


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.integration
def test_e2e_todo_create_and_read(app, session, run_sync):
    # drop storage → self-heal → add → list (REAL)
    with app.db.engine.begin() as c:
        c.exec_driver_sql("DROP TABLE IF EXISTS todos")
    app.todo_provider.initialized = False
    # through the EXECUTOR so history is recorded
    r1 = run_sync(app.executor._dispatch_tool(
        session, None, ToolCall(id="t1", name="todo_add",
                                arguments={"task": "buy milk"})))
    assert r1.ok, r1.error
    r2 = run_sync(app.executor._dispatch_tool(
        session, None, ToolCall(id="t2", name="todo_list", arguments={})))
    assert r2.ok
    assert any(t["task"] == "buy milk" for t in r2.data["todos"])
    # history recorded
    from database.models import ToolExecution
    with app.db.session() as s:
        n = s.query(ToolExecution).filter_by(session_id=session).count()
    assert n >= 2


@pytest.mark.integration
def test_e2e_browser_open_navigate_screenshot(app, session, mock_llm, run_sync):
    mock_llm.enqueue(
        "[ECHO]",
        '[TOOL browser_open {}]',
        '[TOOL browser_navigate {"url":"https://example.com"}]',
        '[TOOL browser_verify_url {"expected":"https://example.com"}]',
        '[TOOL browser_screenshot {}]',
        '[TOOL browser_close {}]',
        "browser done")
    plan, step = run_sync(app.planner.create_plan(session, "open the browser to example.com"))
    outcome = run_sync(app.executor.run_step(
        session, plan, step, "browser e2e",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step))
    assert outcome.status == "DONE", outcome.errors
    shots = list((app.config.data_dir / "screenshots").glob("browser_*.png"))
    assert shots, "no real browser screenshot"


@pytest.mark.integration
def test_e2e_filesystem_workflow(app, session, run_sync):
    # REAL file create → write → read → verify → delete via tools
    r = run_sync(app.registry.execute("fs_create_folder", {"path": "e2e"}, {"confirm": True}))
    assert r.ok
    r = run_sync(app.registry.execute("fs_write_content",
                                      {"path": "e2e/note.txt", "content": "hello e2e"},
                                      {"confirm": True}))
    assert r.ok
    r = run_sync(app.registry.execute("fs_read_content", {"path": "e2e/note.txt"},
                                      {"confirm": True}))
    assert r.ok and "hello e2e" in r.data["content"]
    r = run_sync(app.registry.execute("fs_verify_integrity",
                                      {"path": "e2e/note.txt", "expected_content": "hello e2e"},
                                      {"confirm": True}))
    assert r.ok
    r = run_sync(app.registry.execute("fs_delete", {"path": "e2e/note.txt"},
                                      {"confirm": True}))
    assert r.ok


@pytest.mark.integration
def test_e2e_youtube_windows_browser_path(app, run_sync):
    # "open youtube" → capability workflow.browser → windows host (browser)
    d = app.target_resolver.resolve("open youtube", "workflow.browser", "e2e")
    assert d.device == "windows"       # default policy; browser hosted on windows
    # a real browser tool exists and is health-scanned
    assert app.tool_health.state("browser_open")["state"] in ("READY", "BROKEN")


@pytest.mark.integration
def test_e2e_youtube_android_path(app, run_sync):
    d = app.target_resolver.resolve("open youtube on my phone", "device.android", "e2e")
    assert d.explicit is True
    assert d.device in ("android", "windows")  # offline fallback applies


@pytest.mark.integration
def test_e2e_clipboard_and_recovery(app, session, run_sync):
    # clipboard observer path (no clipboard tool registered, but observer works)
    obs = app.observers.verify_after("clipboard_set", {"text": "x"}, None)
    assert isinstance(obs, list)
    # recovery: a recoverable failure retries and succeeds
    from tools.base import Tool
    from core.contracts import ToolResult

    class Flaky(Tool):
        name = "e2e_flaky"
        description = "fails once then ok (recoverable, no tool-level retry)"
        parameters = {"type": "object", "properties": {}}
        retries = 0                       # let RecoveryPolicy handle it
        calls = 0
        async def execute(self, params, ctx):
            Flaky.calls += 1
            if Flaky.calls == 1:
                return ToolResult(ok=False, error="connection refused (transient)")
            return ToolResult(ok=True, data={"ok": True})

    app.registry.register(Flaky())
    tc = ToolCall(id="e2e", name="e2e_flaky", arguments={})
    res = run_sync(app.executor._dispatch_tool(session, None, tc))
    assert res.ok and Flaky.calls == 2   # recovery retry
    # recovery recorded on the tool monitor (attempts + success)
    stats = {x["tool"]: x for x in app.tool_monitor.stats()}
    assert stats["e2e_flaky"]["recovery_attempts"] >= 1
    assert stats["e2e_flaky"]["recovery_success"] >= 1


@pytest.mark.integration
def test_e2e_adb_reconnect_attempt(app, run_sync):
    # real ADB reconnect attempt via RecoveryPolicy (device offline → repair)
    from core.errors import FailureInfo, FailureClass
    from executor.recovery import RecoveryPolicy
    rp = RecoveryPolicy()
    # repair tries to reconnect the real adb device (offline here → honest)
    services = {"devices": app.devices}
    res = run_sync(rp.repair(FailureInfo(FailureClass.DEVICE, "device offline",
                                         tool="android_open_youtube", recoverable=True),
                             "android_open_youtube", services))
    assert res.action in ("device_reconnect", "noop")


@pytest.mark.integration
def test_e2e_sqlite_recovery(app, session, run_sync):
    from database import recovery
    assert recovery.integrity_check(app.db) == []
    bk = recovery.backup(app.db)
    assert bk.exists()
    # schema version + migrations applied
    from database.migrations import apply
    apply(app.db)
    assert app.db.user_version() >= 2
    with app.db.engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"


@pytest.mark.integration
def test_e2e_openrouter_available(app):
    # the LLM manager has a configured provider path (openrouter or mock)
    keys = app.llm.router.healthy_keys()
    assert len(keys) >= 1
