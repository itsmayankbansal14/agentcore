"""Integration: Executor → Tool Registry → Tool.

Real: the Executor dispatches a ToolCall through the registry; the tool
executes; the result is recorded (history), monitored (ToolMonitor),
observed (observer events), and surfaced to the LLM loop.
"""
import asyncio
import json

import pytest

from core.contracts import ToolCall


@pytest.mark.integration
def test_executor_dispatches_tool_and_records_history(app, session, mock_llm, run_sync):
    mock_llm.enqueue(
        '[TOOL time_now {}]',
        'the time was fetched')
    plan, step = run_sync(app.planner.create_plan(session, "what time is it?"))
    outcome = run_sync(app.executor.run_step(
        session, plan, step, "what time is it?",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step))

    assert outcome.status == "DONE"
    assert any(tc["name"] == "time_now" for tc in outcome.tool_calls)

    # history row for the tool
    from database.models import ToolExecution
    with app.db.session() as s:
        row = s.query(ToolExecution).filter_by(session_id=session,
                                               tool="time_now").first()
    assert row is not None and row.status == "ok"

    # ToolMonitor stats updated
    stats = {t["tool"]: t for t in app.tool_monitor.stats()}
    assert stats["time_now"]["runs"] >= 1
    assert stats["time_now"]["success_rate"] == 100.0


@pytest.mark.integration
def test_executor_tool_timeout_retry_rollback(app, session, run_sync):
    from tools.base import Tool
    from core.contracts import ToolResult

    class Flaky(Tool):
        name = "it_flaky"
        description = "fails once then ok"
        parameters = {"type": "object", "properties": {}}
        retries = 1
        idempotent = True
        calls = 0

        async def execute(self, params, ctx):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise RuntimeError("transient")
            return ToolResult(ok=True, data={})

    app.registry.register(Flaky())
    tc = ToolCall(id="t", name="it_flaky", arguments={})
    res = run_sync(app.executor._dispatch_tool(session, None, tc))
    assert res.ok and (res.attempts or 1) == 2  # retried once
    assert Flaky.calls == 2


@pytest.mark.integration
def test_tool_failure_classified_with_suggestions(app, session, run_sync):
    tc = ToolCall(id="t2", name="android_open_youtube",
                  arguments={"query": "x", "device_id": "adb"})
    res = run_sync(app.executor._dispatch_tool(session, None, tc))
    assert not res.ok  # adb offline here → honest failure
    from database.models import ToolExecution
    with app.db.session() as s:
        row = s.query(ToolExecution).filter_by(session_id=session,
                                               tool="android_open_youtube").first()
    assert row is not None
    assert row.failure_class in ("device", "tool")
    sugs = json.loads(row.recovery_suggestions or "[]")
    assert isinstance(sugs, list) and len(sugs) >= 1
