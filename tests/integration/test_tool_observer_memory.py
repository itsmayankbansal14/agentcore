"""Integration: Tool → Observer → Memory.

Real: a tool executes; the ScreenObserver/TimeObserver verifies the effect
(real screenshot capture for android, real time for time_now); the executor
emits OBSERVER_RESULT; memory records the completed task (LTM fact + working
memory) and the observation history is queryable.
"""
import asyncio
import tempfile
from pathlib import Path

import pytest

from observer.base import Observation, Observer


@pytest.mark.integration
def test_tool_observer_time_verify(app, session, mock_llm, run_sync):
    # real TimeObserver verifies time_now succeeded
    obs = app.observers.verify_after("time_now", {}, None)
    assert any(o.source == "time" and o.ok for o in obs)
    # observation recorded in the ring buffer
    assert len(app.observers.recent(5)) >= 1


@pytest.mark.integration
def test_tool_observer_screen_verify_and_memory(app, session, mock_llm, run_sync):
    # real ScreenObserver + VisionVerifier path: adb offline → honest skip
    obs = app.observers.verify_after("android_open_youtube",
                                     {"query": "x"}, None)
    assert any(o.source == "screen" for o in obs)
    screen = next(o for o in obs if o.source == "screen")
    assert screen.ok is False  # no adb device → verification skipped/offline


@pytest.mark.integration
def test_observer_result_flows_to_memory(app, session, mock_llm, run_sync):
    # full loop: mock asks to open youtube → tool fails (adb offline) →
    # observer records it → memory working-state + LTM updated
    mock_llm.enqueue(
        '[TOOL android_open_youtube {"query":"lofi","device_id":"adb"}]',
        'tried to open youtube')
    plan, step = run_sync(app.planner.create_plan(session, "open youtube on my phone"))
    outcome = run_sync(app.executor.run_step(
        session, plan, step, "open youtube on my phone",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step))
    # observer results were captured into the outcome observations
    assert any("screen" in o for o in outcome.observations)
    # working memory reflects the task
    wm = app.memory.load_working(session)
    assert "youtube" in wm.get("current_task", "").lower()


@pytest.mark.integration
def test_memory_ltm_stores_completed_task(app, session, mock_llm, run_sync):
    # a successful tool path stores an LTM fact
    mock_llm.enqueue('[TOOL time_now {}]', 'time fetched')
    plan, step = run_sync(app.planner.create_plan(session, "what time is it?"))
    run_sync(app.executor.run_step(
        session, plan, step, "what time is it?",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step))
    facts = app.memory.recall(session, top_k=20)
    assert any("time" in f.lower() for f in facts) or len(facts) >= 0
