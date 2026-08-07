"""Integration: Windows workflows (WindowsDevice = local machine as a device).

Real: WindowsDevice routes capability commands into the local tool registry
(filesystem tools in the sandbox, time, etc.); sandboxed file operations
actually write/read files; the same commands work through the agent loop.
"""
import pytest


@pytest.mark.integration
def test_windows_device_executes_local_tools(app, run_sync):
    win = app.devices.get("windows")
    assert win is not None and win.health()["online"] is True
    res = run_sync(win.execute("time_now", {}))
    assert res.ok and "now" in (res.data or {})
    res2 = run_sync(win.execute("fs_list", {"path": "."}))
    assert res2.ok


@pytest.mark.integration
def test_windows_filesystem_tools_real_io(app, run_sync):
    # real sandboxed file write + read + list
    r = run_sync(app.registry.execute("fs_write",
                                      {"path": "it_probe.txt", "content": "hello"},
                                      {"confirm": True}))
    assert r.ok
    from pathlib import Path
    sandbox = app.config.data_dir / "sandbox"
    assert (sandbox / "it_probe.txt").exists()
    r2 = run_sync(app.registry.execute("fs_read", {"path": "it_probe.txt"},
                                       {"confirm": True}))
    assert r2.ok and "hello" in r2.data["content"]
    r3 = run_sync(app.registry.execute("fs_list", {"path": "."},
                                       {"confirm": True}))
    assert any(i["name"] == "it_probe.txt" for i in r3.data["items"])


@pytest.mark.integration
def test_windows_device_through_agent_loop(app, session, mock_llm, run_sync):
    mock_llm.enqueue('[TOOL time_now {}]', 'the time is now')
    plan, step = run_sync(app.planner.create_plan(session, "what time is it?"))
    outcome = run_sync(app.executor.run_step(
        session, plan, step, "what time is it?",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step))
    assert outcome.status == "DONE"
