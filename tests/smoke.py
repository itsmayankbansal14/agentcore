"""AgentCore — tests/smoke.py
End-to-end smoke tests against the MockProvider (no API keys needed).
Run: python tests/smoke.py   (from the agentcore root)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.app import AgentApp
from core.contracts import LLMMessage, Role
from llm.providers import MockProvider, RateLimitError
from llm.router import KeyRuntime, LLMRouter

PASS = 0
FAIL = 0


def fresh_app():
    """Isolated app per test (own temp DB) so tests never contaminate each other.
    Forced to mock-only keys so the suite stays hermetic even with real keys in .env."""
    import tempfile
    from llm.router import KeyRuntime
    app = AgentApp.create(db_path=tempfile.mktemp(suffix=".db"))
    app.llm.router.keys = [KeyRuntime(provider="mock", key="mock-key", model="mock-1")]
    return app


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


async def test_conversation_and_tool_loop() -> None:
    print("\n[1] Conversation + tool loop (mock)")
    app = fresh_app()
    provider = MockProvider()
    app.llm._factory = lambda name, key, model: provider  # scripted provider
    provider.enqueue('[TOOL time_now {}]', '[ECHO]')
    out = await app.orchestrator.handle_user_message("demo", "What time is it?")
    check("final answer returned", bool(out))
    with app.db.session() as s:
        from database.models import ToolExecution
        rows = s.query(ToolExecution).filter(ToolExecution.tool == "time_now").all()
        check("time_now executed and recorded", len(rows) >= 1, f"rows={len(rows)}")
    check("answer mentions time", "time" in out.lower() or "mock" in out.lower())


async def test_router_failover() -> None:
    print("\n[2] Router failover + key rotation")
    good = MockProvider(model="good", api_key="k1")
    good.enqueue("[ECHO]")
    bad = MockProvider(model="bad", api_key="k2")
    bad.fail_rate_once = True  # first call raises RateLimit

    calls: list[str] = []

    def factory(name, key, model):
        calls.append(f"{name}:{model}")
        return good if name == "good" else bad

    keys = [KeyRuntime("bad", "k2", "bad"), KeyRuntime("good", "k1", "good")]
    router = LLMRouter(keys, cooldown_seconds=10)
    resp = await router.chat(factory, [LLMMessage(role=Role.USER, content="hi")])
    check("failover to second provider", resp.provider == "mock" and "good" in calls[-1],
          f"calls={calls}")
    # bad key now in cooldown
    check("rate-limited key in cooldown", keys[0].cooldown_until > 0)
    # second call should skip the bad key entirely
    calls.clear()
    bad.fail_rate_once = True
    await router.chat(factory, [LLMMessage(role=Role.USER, content="hi again")])
    check("cooldown skips bad key", "bad" not in calls, f"calls={calls}")


async def test_memory_persistence() -> None:
    print("\n[3] Memory persists across 'restart'")
    app1 = fresh_app()
    provider = MockProvider()
    app1.llm._factory = lambda name, key, model: provider
    provider.enqueue("[ECHO]")
    await app1.orchestrator.handle_user_message("sess_persist", "remember that I love Python")
    provider.enqueue("[ECHO]")
    await app1.orchestrator.handle_user_message("sess_persist", "second message")

    # simulate restart: new app instance, same DB
    db_path = app1.db.path
    app2 = AgentApp.create(db_path=str(db_path))
    history = app2.memory.load_history("sess_persist")
    check("history survives restart", len(history) >= 4, f"msgs={len(history)}")
    working = app2.memory.load_working("sess_persist")
    check("working memory survives restart", working.get("current_task") != "")


async def test_plan_and_resume() -> None:
    print("\n[4] Planner: decompose + resume after crash")
    app = fresh_app()
    app.orchestrator.ensure_session("sess_plan")
    plan, step = await app.planner.create_plan(
        "sess_plan",
        "Build a flask app then create a README then commit to git then zip it")
    check("multi-step plan created", plan is not None and len(plan.steps) >= 2,
          f"steps={len(plan.steps) if plan else 0}")
    if plan:
        # simulate: step 1 running, crash
        app.planner.set_step_status(plan.steps[0].id, _st("RUNNING"))
        # resume marks interrupted, returns first actionable
        resumed_plan, next_step = app.planner.resume("sess_plan")
        with app.db.session() as s:
            from database.models import PlanStep
            s1 = s.get(PlanStep, plan.steps[0].id)
            check("RUNNING → INTERRUPTED after resume",
                  s1.status == "INTERRUPTED" and next_step is not None,
                  f"status={s1.status}")


def _st(name: str):
    from planner.steps import StepStatus
    return StepStatus[name]


async def test_devices() -> None:
    print("\n[5] Device abstraction")
    app = fresh_app()
    win = app.devices.get("windows")
    check("WindowsDevice online", win.health()["online"])
    res = await win.execute("time_now", {})
    check("WindowsDevice executes local tool", res.ok, res.error or "")
    android = app.devices.get("android")
    check("AndroidDevice offline (phase 5)", android.health()["online"] is False)
    res2 = await android.execute("device.android.open_app", {"app": "whatsapp"})
    check("Android offline → structured BLOCKED", not res2.ok and res2.data.get("blocked"))


async def test_registry_search() -> None:
    print("\n[6] Tool registry search (no keyword dispatch)")
    app = fresh_app()
    hits = app.registry.search("read file contents")
    names = [s.name for s in hits]
    check("search finds fs_read", "fs_read" in names, str(names[:5]))
    hits2 = app.registry.search("current time")
    check("search finds time_now", any("time" in s.name for s in hits2), str([s.name for s in hits2]))


async def test_ltm_extraction() -> None:
    print("\n[7] LTM: fact extraction + dedup + recall")
    app = fresh_app()
    n = app.memory.remember_from_message(
        "sess_ltm", "My name is Aman and I live in Jaipur")
    check("extracted facts", n >= 2, f"count={n}")
    facts = app.memory.recall("sess_ltm", top_k=20)
    joined = " | ".join(facts)
    check("name extracted", "user.name" in joined and "Aman" in joined, joined[:120])
    check("location extracted", "user.location" in joined and "Jaipur" in joined, joined[:120])
    # dedup: re-remember same name should not duplicate the row
    app.memory.remember("sess_ltm", "identity", "user.name", "Aman", source="test")
    with app.db.session() as s:
        from database.models import LongTermMemory
        rows = s.query(LongTermMemory).filter(
            LongTermMemory.key == "user.name",
            LongTermMemory.session_id == "sess_ltm").all()
        check("ltm dedup by key (per session)", len(rows) == 1, f"rows={len(rows)}")


async def test_knowledge_indexing() -> None:
    print("\n[8] Knowledge: ingest + lexical/vector search")
    app = fresh_app()
    path = Path(app.config.data_dir) / "sandbox" / "test_knowledge.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "Binary search finds items in a sorted list in O(log n). "
        "Hashmaps give O(1) lookups. The student lives in Jaipur and codes daily.")
    result = await app.memory.add_knowledge(str(path))
    check("file indexed", result.get("ok") and result.get("chunks", 0) >= 1, str(result))
    hits = await app.memory.search_knowledge("binary search sorted list")
    check("lexical search hits", any("Binary search" in h for h in hits), str(hits[:1]))
    hits2 = await app.memory.search_knowledge("Jaipur student")
    check("multi-term search hits", len(hits2) >= 1, str(hits2[:1]))


async def test_life_tools() -> None:
    print("\n[9] Life tools (SQLite-backed todos/habits/expenses)")
    app = fresh_app()
    r = await app.registry.execute("todo_add", {"task": "finish DSA", "priority": "high"}, {})
    check("todo_add", r.ok and r.data["id"] == 1, str(r.data))
    r = await app.registry.execute("todo_list", {}, {})
    check("todo_list", r.ok and r.data["count"] == 1, str(r.data))
    r = await app.registry.execute("todo_done", {"id": 1}, {})
    check("todo_done", r.ok, str(r.data))
    r = await app.registry.execute("habit_add", {"name": "coding"}, {})
    check("habit_add", r.ok, str(r.data))
    r = await app.registry.execute("habit_check", {"name": "coding"}, {})
    check("habit_check streak 1", r.ok and r.data["streak"] == 1, str(r.data))
    r = await app.registry.execute("expense_add", {"amount": 150, "category": "food"}, {})
    check("expense_add", r.ok, str(r.data))
    r = await app.registry.execute("expense_summary", {}, {})
    check("expense_summary", r.ok and r.data["total"] == 150.0, str(r.data))


async def test_migration_script() -> None:
    print("\n[10] JARVIS JSON → SQLite migration")
    import tempfile
    import json as _json
    from scripts.migrate_jarvis import migrate
    tmp = Path(tempfile.mkdtemp())
    data = tmp / "data"; data.mkdir()
    (data / "todos.json").write_text(_json.dumps([
        {"id": 1, "task": "finish project", "priority": "medium", "done": False},
        {"id": 2, "task": "read DSA", "priority": "high", "done": True}]))
    (data / "habits.json").write_text(_json.dumps([
        {"id": 1, "name": "coding", "streak": 3, "history": ["2026-08-01"]}]))
    (data / "expenses.json").write_text(_json.dumps([
        {"amount": 200, "category": "food", "note": "lunch"}]))
    app = fresh_app()
    report = migrate(tmp, app.db, dry_run=False, force=False)
    check("migrated counts", report["todos"] == 2 and report["habits"] == 1
          and report["expenses"] == 1, str(report))
    with app.db.session() as s:
        from database.models import Todo, Habit, Expense
        check("todos in sqlite", s.query(Todo).count() == 2)
        check("habits in sqlite", s.query(Habit).count() == 1)
        check("expenses in sqlite", s.query(Expense).count() == 1)
        t2 = s.query(Todo).filter_by(task="read DSA").first()
        check("done flag preserved", t2 is not None and t2.done is True)


async def test_planner_retry_block() -> None:
    print("\n[11] Planner: retry cap → BLOCKED")
    app = fresh_app()
    app.orchestrator.ensure_session("sess_retry")
    plan, step = await app.planner.create_plan("sess_retry", "simple single goal")
    # simulate repeated failures
    for _ in range(4):
        app.planner.set_step_status(step.id, _st("RUNNING"))
        app.planner.set_step_status(step.id, _st("FAILED"))
    nxt = app.planner.next_step(plan)
    check("exhausted retries → BLOCKED, no next step",
          nxt is None, f"next={nxt}")
    with app.db.session() as s:
        from database.models import PlanStep
        st = s.get(PlanStep, step.id)
        check("step status BLOCKED", st.status == "BLOCKED", st.status)


def main() -> None:
    asyncio.run(test_conversation_and_tool_loop())
    asyncio.run(test_router_failover())
    asyncio.run(test_memory_persistence())
    asyncio.run(test_plan_and_resume())
    asyncio.run(test_devices())
    asyncio.run(test_registry_search())
    asyncio.run(test_ltm_extraction())
    asyncio.run(test_knowledge_indexing())
    asyncio.run(test_life_tools())
    asyncio.run(test_migration_script())
    asyncio.run(test_planner_retry_block())
    print(f"\n{'='*40}\nPASSED: {PASS}   FAILED: {FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
