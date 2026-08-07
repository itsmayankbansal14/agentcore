"""AgentCore — tests/test_architecture.py
Tests for the Phase-1/2 architectural improvements:
  Reasoner, Executor (retries/timeout/cancel/parallel), ExecutionPolicy,
  Observer, PermissionManager, task lifecycle, execution history, DB recovery.
Run: python tests/test_architecture.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.app import AgentApp
from core.contracts import LLMMessage, Role
from core.permissions import Decision, PermissionManager
from database import recovery
from executor.executor import Executor
from executor.policy import BudgetTracker, ExecutionPolicy
from llm.router import KeyRuntime
from llm.providers import MockProvider
from observer.base import Observation
from planner.steps import StepStatus, can_transition
from reasoning.base import Decomposition
from reasoning.llm import LLMReasoner
from reasoning.local_human import HumanReasoner, LocalReasoner

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def fresh_app():
    app = AgentApp.create(db_path=tempfile.mktemp(suffix=".db"))
    app.llm.router.keys = [KeyRuntime(provider="mock", key="mock-key", model="mock-1")]
    return app


# ---------------------------------------------------------------------------
async def test_reasoner() -> None:
    print("\n[1] Reasoner interface")
    app = fresh_app()
    # LLMReasoner with a scripted mock
    prov = MockProvider()
    app.llm._factory = lambda n, k, m: prov
    reasoner = LLMReasoner(app.llm)
    prov.enqueue('["step one", "step two", "step three"]')
    dec = await reasoner.decompose("build a flask app then write tests")
    check("LLMReasoner decomposes", dec is not None and len(dec.steps) == 3,
          str(dec))
    check("Decomposition has engine", dec is not None and dec.engine == "llm")
    # LocalReasoner fallback
    local = LocalReasoner()
    dec2 = await local.decompose("do A then do B then do C")
    check("LocalReasoner splits on connectors", dec2 is not None and len(dec2.steps) == 3,
          str(dec2))
    check("LocalReasoner single-step → None", await local.decompose("simple task") is None)
    # HumanReasoner
    calls = {"n": 0}

    def fake_ask(p):
        calls["n"] += 1
        return "step1, step2"
    human = HumanReasoner(ask=fake_ask)
    dec3 = await human.decompose("any goal")
    check("HumanReasoner asks + parses", dec3 is not None and len(dec3.steps) == 2,
          str(dec3))


async def test_executor_retries_and_timeout() -> None:
    print("\n[2] Executor: retries + timeout")
    app = fresh_app()
    prov = MockProvider()
    app.llm._factory = lambda n, k, m: prov
    app.executor.policy.max_retries = 2
    app.executor.policy.step_timeout_s = 0.5
    app.orchestrator.ensure_session("sess_ex")

    # timeout path: provider that never returns
    class SlowMock(MockProvider):
        async def chat(self, *a, **kw):
            await asyncio.sleep(5)
            return await super().chat(*a, **kw)
    app.llm._factory = lambda n, k, m: SlowMock()

    plan, step = await app.planner.create_plan("sess_ex", "do the thing")
    outcome = await app.executor.run_step(
        "sess_ex", plan, step, "do the thing",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step)
    check("timeout → FAILED after retries", outcome.status == "FAILED", outcome.status)
    check("errors recorded", len(outcome.errors) >= 1, str(outcome.errors))
    check("retries attempted", "retries exhausted" in " ".join(outcome.errors),
          str(outcome.errors))

    # success path with a working mock
    app.llm._factory = lambda n, k, m: MockProvider()
    app.executor.policy.step_timeout_s = 30
    prov2 = MockProvider(); app.llm._factory = lambda n, k, m: prov2
    prov2.enqueue("[ECHO]")
    app.orchestrator.ensure_session("sess_ex2")
    plan2, step2 = await app.planner.create_plan("sess_ex2", "hello world task")
    out2 = await app.executor.run_step(
        "sess_ex2", plan2, step2, "hello world task",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_id=plan2.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step)
    check("success → DONE", out2.status == "DONE", out2.status)
    check("budget tracked", out2.budget.get("steps", 0) >= 1, str(out2.budget))


async def test_executor_cancellation() -> None:
    print("\n[3] Executor: cancellation")
    app = fresh_app()

    class SlowMock(MockProvider):
        async def chat(self, *a, **kw):
            await asyncio.sleep(30)
            return await super().chat(*a, **kw)
    app.llm._factory = lambda n, k, m: SlowMock()
    app.orchestrator.ensure_session("sess_cx")
    plan, step = await app.planner.create_plan("sess_cx", "run forever task")

    task = asyncio.create_task(app.executor.run_step(
        "sess_cx", plan, step, "run forever task",
        system_prompt_builder=lambda sid, pl: "sys"))
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
        status = "no-exc"
    except asyncio.CancelledError:
        status = "cancelled"
    check("CancelledError propagates", status == "cancelled")
    from database.models import Execution
    with app.db.session() as s:
        rows = s.query(Execution).filter_by(step_id=step.id).all()
    check("execution history records CANCELLED",
          rows and rows[-1].status == "CANCELLED", str([r.status for r in rows]))


async def test_executor_parallel() -> None:
    print("\n[4] Executor: parallel independent steps")
    app = fresh_app()
    prov = MockProvider(); app.llm._factory = lambda n, k, m: prov
    app.orchestrator.ensure_session("sess_par")
    plan, _ = await app.planner.create_plan("sess_par", "task one then task two")
    with app.db.session() as s:
        from database.models import PlanStep
        steps = s.query(PlanStep).filter_by(plan_id=plan.id).order_by(PlanStep.order_idx).all()
    # make step1 slow so step2 (independent) runs concurrently
    from planner.steps import StepStatus as SS

    class SlowFirst(MockProvider):
        async def chat(self, *a, **kw):
            if len(a) > 0 and any(m.content and "task one" in str(m.content) for m in a[0] if m.content):
                await asyncio.sleep(0.8)
            return await super().chat(*a, **kw)
    app.llm._factory = lambda n, k, m: SlowFirst()
    t0 = time.time()
    outcomes = await app.executor.run_plan(
        "sess_par", plan, "task one then task two",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_completer=app.planner.mark_plan_completed)
    elapsed = time.time() - t0
    check("both steps executed", len(outcomes) == 2, str(len(outcomes)))
    check("all DONE", all(o.status == "DONE" for o in outcomes),
          str([o.status for o in outcomes]))
    check("ran in parallel (<1.5s for 0.8s+0s)", elapsed < 1.5, f"{elapsed:.2f}s")


async def test_execution_policy() -> None:
    print("\n[5] ExecutionPolicy / BudgetTracker")
    policy = ExecutionPolicy(max_steps=2, max_tokens=1000, max_cost=0.05)
    bt = BudgetTracker(policy)
    check("within budget initially", bt.check() is None)
    bt.steps_taken = 2
    check("max_steps triggers", bt.check() == "max_steps exceeded (2)", bt.check())
    bt2 = BudgetTracker(ExecutionPolicy(max_tokens=1000))
    bt2.record("openrouter", 600, 600)  # 1200 tokens > 1000
    check("max_tokens triggers", bt2.check() == "max_tokens exceeded (1000)",
          bt2.check())
    bt3 = BudgetTracker(ExecutionPolicy(max_cost=0.01, max_tokens=0))  # 0 = unlimited
    bt3.record("openrouter", 1_000_000, 0)  # $0.15 > $0.01
    check("max_cost triggers", bt3.check() == "max_cost exceeded ($0.1500)",
          bt3.check())


async def test_observer() -> None:
    print("\n[6] Observer subsystem")
    app = fresh_app()
    obs = app.observers
    # filesystem verify
    path = Path(tempfile.mkdtemp()) / "probe.txt"
    path.write_text("x")
    res = obs.verify_after("fs_write", {"path": str(path)}, {"path": str(path)})
    check("filesystem verify finds file",
          any(o.source == "filesystem" and o.ok for o in res), str(res))
    res2 = obs.verify_after("fs_write", {"path": str(path) + ".missing"}, {})
    check("filesystem verify flags missing",
          any(o.source == "filesystem" and not o.ok for o in res2), str(res2))
    # time verify
    res3 = obs.verify_after("time_now", {}, {})
    check("time verify", any(o.source == "time" and o.ok for o in res3), str(res3))
    # poll gives snapshots
    polls = obs.poll()
    check("poll returns snapshots", len(polls) >= 1, str([p.source for p in polls]))


async def test_permissions() -> None:
    print("\n[7] PermissionManager: allowed / confirm / denied")
    from core.contracts import Permission, ToolSpec
    from core.permissions import PermissionResult
    app = fresh_app()
    pm = PermissionManager(app.config)  # no confirm callback → CONFIRM downgrades to DENIED
    spec_always = ToolSpec(name="time_now", description="", parameters={},
                           permission=Permission.ALWAYS)
    spec_confirm = ToolSpec(name="shell_run", description="", parameters={},
                            permission=Permission.USER_CONFIRM)
    check("always-allowed tool", pm.check(spec_always, "time_now").decision == Decision.ALLOWED)
    r = pm.check(spec_confirm, "shell_run")
    check("confirm-without-UI → DENIED", r.decision == Decision.DENIED, r.reason)
    # with a callback
    pm2 = PermissionManager(app.config, confirm_callback=lambda n, a: True)
    check("confirm callback allows", pm2.check(spec_confirm, "shell_run").decision == Decision.ALLOWED)
    pm3 = PermissionManager(app.config, confirm_callback=lambda n, a: False)
    check("confirm callback denies", pm3.check(spec_confirm, "shell_run").decision == Decision.DENIED)
    # config denylist
    app.config.set_runtime("tools.denylist", ["todo_add"])
    r = pm.check(app.registry.get_spec("todo_add"), "todo_add")
    check("denylist denies", r.decision == Decision.DENIED, r.reason)


async def test_task_lifecycle() -> None:
    print("\n[8] Task lifecycle state machine")
    check("CREATED→PLANNING", can_transition(StepStatus.CREATED, StepStatus.PLANNING))
    check("PLANNING→PENDING", can_transition(StepStatus.PLANNING, StepStatus.PENDING))
    check("PENDING→RUNNING", can_transition(StepStatus.PENDING, StepStatus.RUNNING))
    check("RUNNING→OBSERVING", can_transition(StepStatus.RUNNING, StepStatus.OBSERVING))
    check("OBSERVING→DONE", can_transition(StepStatus.OBSERVING, StepStatus.DONE))
    check("RUNNING→RETRYING", can_transition(StepStatus.RUNNING, StepStatus.RETRYING))
    check("RETRYING→RUNNING", can_transition(StepStatus.RETRYING, StepStatus.RUNNING))
    check("RUNNING→CANCELLED", can_transition(StepStatus.RUNNING, StepStatus.CANCELLED))
    check("DONE→CANCELLED forbidden", not can_transition(StepStatus.DONE, StepStatus.CANCELLED))
    # integration: a real step through RUNNING → OBSERVING → DONE
    app = fresh_app()
    app.orchestrator.ensure_session("sess_lc")
    plan, step = await app.planner.create_plan("sess_lc", "lifecycle test")
    from database.models import PlanStep
    app.planner.set_step_status(step.id, StepStatus.PLANNING)
    app.planner.set_step_status(step.id, StepStatus.PENDING)
    app.planner.set_step_status(step.id, StepStatus.RUNNING)
    app.planner.set_step_status(step.id, StepStatus.OBSERVING)
    app.planner.set_step_status(step.id, StepStatus.DONE)
    with app.db.session() as s:
        st = s.get(PlanStep, step.id)
        check("step ended DONE", st.status == "DONE", st.status)


async def test_execution_history() -> None:
    print("\n[9] Persistent execution history")
    app = fresh_app()
    prov = MockProvider(); app.llm._factory = lambda n, k, m: prov
    prov.enqueue("[ECHO]")
    app.orchestrator.ensure_session("sess_hist")
    plan, step = await app.planner.create_plan("sess_hist", "history goal")
    await app.executor.run_step("sess_hist", plan, step, "history goal",
                                system_prompt_builder=lambda sid, pl: "sys",
                                plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
                                next_step_provider=app.planner.next_step)
    from database.models import Execution
    with app.db.session() as s:
        rows = s.query(Execution).filter_by(session_id="sess_hist").all()
    check("execution row persisted", len(rows) == 1)
    row = rows[0]
    check("status DONE", row.status == "DONE", row.status)
    check("goal recorded", row.goal == "history goal")
    check("duration recorded", row.duration_ms >= 0)
    check("result recorded", bool(row.result), str(row.result))


async def test_db_recovery() -> None:
    print("\n[10] SQLite recovery: integrity, backup, migration")
    app = fresh_app()
    problems = recovery.integrity_check(app.db)
    check("integrity clean", problems == [], str(problems))
    bk = recovery.backup(app.db)
    check("backup created", bk.exists() and bk.stat().st_size > 0, str(bk))
    # simulate column migration on an existing db
    with app.db.engine.connect() as c:
        cols = {r[1] for r in c.exec_driver_sql("PRAGMA table_info(tool_executions)").all()}
    check("duration_ms column exists", "duration_ms" in cols)
    check("schema version set", app.db.user_version() >= 2, str(app.db.user_version()))


def main() -> None:
    asyncio.run(test_reasoner())
    asyncio.run(test_executor_retries_and_timeout())
    asyncio.run(test_executor_cancellation())
    asyncio.run(test_executor_parallel())
    asyncio.run(test_execution_policy())
    asyncio.run(test_observer())
    asyncio.run(test_permissions())
    asyncio.run(test_task_lifecycle())
    asyncio.run(test_execution_history())
    asyncio.run(test_db_recovery())
    print(f"\n{'='*40}\nPASSED: {PASS}   FAILED: {FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
