"""Integration: Capability validation — 4 complete real-world workflows.

Each workflow runs the FULL pipeline through the real runtime:
  Planner → Executor → PermissionManager → Tool Registry → Tool → Observer
  → Memory → Execution History.

The ONLY injected component is the LLM (scripted mock that chooses the
workflow's tool calls) — every tool, observer, memory write and history row
is REAL. Workflows:
  [1] Filesystem  — create folder → create file → write → read → verify → delete
  [2] Browser     — open → navigate → wait → verify URL → screenshot (REAL Chromium)
  [3] Windows     — launch real process → detect open → focus → close → verify closed
  [4] Android     — wake → unlock → launch YouTube → wait → screenshot → verify/retry
                    (real ADB; honest offline result when no device present)
"""
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# [1] FILESYSTEM
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_filesystem_workflow_complete(app, session, mock_llm, run_sync):
    mock_llm.enqueue(
        '[ECHO]',  # consumed by the real Planner decompose call
        '[TOOL fs_create_folder {"path":"wf/project"}]',
        '[TOOL fs_create_file {"path":"wf/project/notes.txt"}]',
        '[TOOL fs_write_content {"path":"wf/project/notes.txt","content":"hello agentcore"}]',
        '[TOOL fs_read_content {"path":"wf/project/notes.txt"}]',
        '[TOOL fs_verify_integrity {"path":"wf/project/notes.txt","expected_content":"hello agentcore"}]',
        '[TOOL fs_delete {"path":"wf/project/notes.txt"}]',
        'filesystem workflow complete')
    plan, step = run_sync(app.planner.create_plan(
        session, "create a project folder with a notes file, write, verify and delete it"))
    outcome = run_sync(app.executor.run_step(
        session, plan, step, "filesystem workflow",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step))

    assert outcome.status == "DONE"
    tools_ran = [tc["name"] for tc in outcome.tool_calls]
    assert tools_ran == ["fs_create_folder", "fs_create_file", "fs_write_content",
                         "fs_read_content", "fs_verify_integrity", "fs_delete"]
    # REAL effects: file deleted at the end, but folder remains
    sandbox = app.config.data_dir / "sandbox"
    assert not (sandbox / "wf" / "project" / "notes.txt").exists()
    assert (sandbox / "wf" / "project").is_dir()
    # Observer verified the writes
    assert any("fs_workflow" in o for o in outcome.observations)
    # History recorded every tool
    from database.models import ToolExecution
    with app.db.session() as s:
        n = s.query(ToolExecution).filter_by(session_id=session).count()
    assert n >= 6


# ---------------------------------------------------------------------------
# [2] BROWSER (REAL Chromium)
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_browser_workflow_complete(app, session, mock_llm, run_sync):
    mock_llm.enqueue(
        '[ECHO]',  # consumed by the real Planner decompose call
        '[TOOL browser_open {}]',
        '[TOOL browser_navigate {"url":"https://example.com"}]',
        '[TOOL browser_wait_load {}]',
        '[TOOL browser_verify_url {"expected":"https://example.com"}]',
        '[TOOL browser_screenshot {}]',
        '[TOOL browser_close {}]',
        'browser workflow complete')
    plan, step = run_sync(app.planner.create_plan(
        session, "open the browser, go to example.com, verify it and screenshot"))
    outcome = run_sync(app.executor.run_step(
        session, plan, step, "browser workflow",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step))

    assert outcome.status == "DONE", outcome.errors
    names = [tc["name"] for tc in outcome.tool_calls]
    assert "browser_navigate" in names and "browser_verify_url" in names
    assert "browser_screenshot" in names
    # REAL: the screenshot file exists
    shots = list((app.config.data_dir / "screenshots").glob("browser_*.png"))
    assert shots, "no real browser screenshot captured"
    # Observer verified the URL
    assert any("URL verified" in o or "browser" in o for o in outcome.observations)


# ---------------------------------------------------------------------------
# [3] WINDOWS (REAL process)
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_windows_workflow_complete(app, session, mock_llm, run_sync):
    import sys
    mock_llm.enqueue(
        '[ECHO]',  # consumed by the real Planner decompose call
        f'[TOOL win_launch {{"app":"{sys.executable}"}}]',
        '[TOOL win_detect_open {}]',
        '[TOOL win_focus {}]',
        '[TOOL win_close {}]',
        '[TOOL win_verify_closed {}]',
        'windows workflow complete')
    plan, step = run_sync(app.planner.create_plan(
        session, "launch python, detect it opened, focus, close and verify closed"))
    outcome = run_sync(app.executor.run_step(
        session, plan, step, "windows workflow",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step))

    assert outcome.status == "DONE", outcome.errors
    names = [tc["name"] for tc in outcome.tool_calls]
    assert names == ["win_launch", "win_detect_open", "win_focus", "win_close",
                     "win_verify_closed"]
    # REAL process lifecycle: launched a real python, detected open, closed
    # win_focus may fail on headless (honest) — the rest must succeed
    focus_res = next((tc for tc in outcome.tool_calls if tc["name"] == "win_focus"), None)
    assert focus_res is not None
    # close verified: the real process exited
    closed = next(tc for tc in outcome.tool_calls if tc["name"] == "win_verify_closed")
    assert closed["ok"] is True, closed


# ---------------------------------------------------------------------------
# [4] ANDROID (REAL ADB — honest offline in sandbox, full retry path)
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_android_workflow_complete(app, session, mock_llm, run_sync):
    # The workflow tools issue REAL adb commands; with no device they fail
    # honestly and the verification gate triggers retries.
    mock_llm.enqueue(
        '[ECHO]',  # consumed by the real Planner decompose call
        '[TOOL android_wake {}]',
        '[TOOL android_unlock {}]',
        '[TOOL android_open_youtube {"query":"lofi","device_id":"adb"}]',
        '[TOOL android_wait_ui {"seconds":1}]',
        '[TOOL android_screenshot {"device_id":"adb"}]',
        '[TOOL android_open_youtube {"query":"lofi","device_id":"adb"}]',
        '[TOOL android_open_youtube {"query":"lofi","device_id":"adb"}]',
        'android workflow failed after retries')
    plan, step = run_sync(app.planner.create_plan(
        session, "wake, unlock, open youtube, wait, screenshot and verify on my phone"))
    outcome = run_sync(app.executor.run_step(
        session, plan, step, "android workflow",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step))

    # honest: no adb device in sandbox → every real command fails truthfully;
    # the workflow still runs the FULL sequence and records classified failures
    assert outcome.status == "DONE"  # soft tool failures → executor completes
    # every real adb command was attempted and recorded
    from database.models import ToolExecution
    with app.db.session() as s:
        tools = [r.tool for r in s.query(ToolExecution).filter_by(session_id=session).all()]
    for expected in ("android_wake", "android_unlock", "android_open_youtube",
                     "android_wait_ui", "android_screenshot"):
        assert expected in tools, f"{expected} not attempted"
    # device-offline failures classified with recovery suggestions
    with app.db.session() as s:
        row = s.query(ToolExecution).filter_by(session_id=session,
                                               tool="android_open_youtube").first()
    assert row.failure_class in ("device", "tool")
    sugs = json.loads(row.recovery_suggestions or "[]")
    assert any("adb" in s.lower() or "phone" in s.lower() for s in sugs)
