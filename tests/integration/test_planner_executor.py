"""Integration: Planner → Executor (the core task loop).

Real: AgentApp runtime, Planner (creates the plan), Executor (runs the step
with policy/retries), Memory (working state), Execution history.
"""
import pytest

from planner.steps import StepStatus


@pytest.mark.integration
def test_planner_creates_plan_and_executor_runs_it(app, session, mock_llm, run_sync):
    # 1) Planner decomposes the goal into a persisted plan
    plan, step = run_sync(app.planner.create_plan(session, "Open YouTube on my phone"))
    assert plan is not None and step is not None
    assert plan.status == "ACTIVE"
    assert "YouTube" in plan.goal

    # 2) Executor runs the step (mock asks to open youtube → real tool path)
    mock_llm.enqueue(
        '[TOOL android_open_youtube {"query":"lofi","device_id":"adb"}]',
        '[TOOL android_open_youtube {"query":"lofi","device_id":"adb"}]',
        'device offline after retries')
    outcome = run_sync(app.executor.run_step(
        session, plan, step, "Open YouTube on my phone",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_id=plan.id,
        plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step))

    # 3) Executor reported a real terminal status; history recorded the run
    assert outcome.status in (StepStatus.DONE.value, StepStatus.FAILED.value)
    from database.models import Execution
    with app.db.session() as s:
        ex = s.query(Execution).filter_by(session_id=session).first()
    assert ex is not None and ex.status == outcome.status
    assert ex.goal.startswith("Open YouTube")

    # 4) Working memory reflects the task
    wm = app.memory.load_working(session)
    assert "YouTube" in wm.get("current_task", "")


@pytest.mark.integration
def test_planner_resume_continues_plan(app, session, run_sync):
    plan, step = run_sync(app.planner.create_plan(
        session, "build an app then write a README then zip it"))
    assert plan is not None and len(plan.steps) >= 2
    # simulate a crash mid-step
    app.planner.set_step_status(plan.steps[0].id, StepStatus.RUNNING)
    resumed_plan, next_step = app.planner.resume(session)
    assert resumed_plan is not None
    from database.models import PlanStep
    with app.db.session() as s:
        st = s.get(PlanStep, plan.steps[0].id)
    assert st.status == StepStatus.INTERRUPTED.value
    assert next_step is not None and next_step.id == plan.steps[0].id


