"""AgentCore — tests/test_reliability.py
Validates the reliability improvements (no architecture change):

  1. Every tool execution: timeout, retry, cancellation, rollback (where possible)
  2. Structured logs for every execution
  3. Execution history for every execution
  4. Failure classification: planner / tool / device / network / api
  5. Failed executions auto-generate recovery suggestions
Run: python tests/test_reliability.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.errors import FailureClass, classify, suggestions_for
from core.app import AgentApp
from llm.router import KeyRuntime
from tools.base import Tool

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
    app.llm.router.keys = [KeyRuntime("mock", "k", "m")]
    return app


# ---- failure tools ----------------------------------------------------------
class SlowTool(Tool):
    """Exceeds its timeout on purpose."""
    name = "reli_slow"
    description = "sleeps longer than timeout"
    parameters = {"type": "object", "properties": {}}
    timeout_s = 0.3

    async def execute(self, params, ctx):
        await asyncio.sleep(5)
        from core.contracts import ToolResult
        return ToolResult(ok=True, data={})


class FlakyTool(Tool):
    """Fails the first N times, then succeeds (retry)."""
    name = "reli_flaky"
    description = "fails first, succeeds after"
    parameters = {"type": "object", "properties": {}}
    retries = 2
    idempotent = True
    fail_first = 1

    async def execute(self, params, ctx):
        from core.contracts import ToolResult
        if self.fail_first > 0:
            self.fail_first -= 1
            raise RuntimeError("flaky failure")
        return ToolResult(ok=True, data={"ok": True})


class RollbackTool(Tool):
    """Records execution; failure triggers rollback."""
    name = "reli_roll"
    description = "creates a side effect that can be undone"
    parameters = {"type": "object", "properties": {"key": {"type": "string"}}}
    applied: list[str] = []
    rolled_back: list[str] = []

    async def execute(self, params, ctx):
        self.applied.append(params.get("key", ""))
        from core.contracts import ToolResult
        return ToolResult(ok=False, error="deliberate failure after side effect")

    async def rollback(self, params, ctx):
        self.rolled_back.append(params.get("key", ""))


# ---------------------------------------------------------------------------
async def test_tool_timeout() -> None:
    print("\n[1] Tool timeout")
    app = fresh_app()
    app.registry.register(SlowTool())
    res = await app.registry.execute("reli_slow", {}, {"confirm": True})
    check("timeout surfaces as failure", not res.ok, res.error)
    check("error names timeout", "timeout" in (res.error or "").lower(), res.error)
    check("duration recorded", res.duration_ms > 0, str(res.duration_ms))


async def test_tool_retry() -> None:
    print("\n[2] Tool retry (fails once, then succeeds)")
    app = fresh_app()
    flaky = FlakyTool()
    app.registry.register(flaky)
    res = await app.registry.execute("reli_flaky", {}, {"confirm": True})
    check("eventually succeeds", res.ok, res.error)
    check("attempts tracked (>1)", (res.attempts or 1) > 1, str(res.attempts))


async def test_tool_rollback() -> None:
    print("\n[3] Tool rollback on failure (executor invokes it)")
    app = fresh_app()
    rt = RollbackTool()
    app.registry.register(rt)
    from executor.executor import Executor
    from executor.policy import ExecutionPolicy
    # drive through the executor so _dispatch_tool runs the rollback hook
    executor = Executor(app.db, app.llm, app.memory, app.registry, app.observers,
                        ExecutionPolicy(), devices=app.devices)
    from core.contracts import ToolCall
    tc = ToolCall(id="t1", name="reli_roll", arguments={"key": "abc"})
    res = await executor._dispatch_tool("rel", None, tc)
    check("tool failed", not res.ok, res.error)
    check("side effect applied", rt.applied == ["abc"], str(rt.applied))
    check("rollback executed", rt.rolled_back == ["abc"], str(rt.rolled_back))
    # history row records rollback + classification
    from database.models import ToolExecution
    with app.db.session() as s:
        row = s.query(ToolExecution).filter_by(tool="reli_roll").first()
    check("history has rollback=ok", row is not None and row.rollback == "ok",
          row.rollback if row else "none")
    check("history has failure_class", row is not None and row.failure_class,
          row.failure_class if row else "none")


async def test_cancellation() -> None:
    print("\n[4] Cancellation propagates (no hang)")
    app = fresh_app()
    app.registry.register(SlowTool())

    async def run():
        return await app.registry.execute("reli_slow", {}, {"confirm": True})
    task = asyncio.create_task(run())
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
        cancelled = False
    except asyncio.CancelledError:
        cancelled = True
    check("cancelled cleanly", cancelled)


async def test_failure_classification() -> None:
    print("\n[5] Failure classification (planner/tool/device/network/api)")
    cases = [
        ("device offline: 127.0.0.1:5555", FailureClass.DEVICE),
        ("android device not paired", FailureClass.DEVICE),
        ("no android device online (tried ['adb'])", FailureClass.DEVICE),
        ("Connection refused by 1.2.3.4:443", FailureClass.NETWORK),
        ("timeout waiting for socket", FailureClass.NETWORK),
        ("rate limit exceeded (429)", FailureClass.API),
        ("invalid api key provided", FailureClass.API),
        ("openrouter: model not found", FailureClass.API),
        ("could not decompose goal into steps", FailureClass.PLANNER),
        ("unknown tool: foo", FailureClass.TOOL),
        ("permission denied for tool", FailureClass.TOOL),
    ]
    for text, expected in cases:
        info = classify(text, component="executor")
        check(f"'{text[:45]}…' → {expected.value}",
              info.kind == expected, f"got {info.kind.value}")
    # provider-layer errors → API
    from llm.providers import RateLimitError, AuthError
    check("RateLimitError → api", classify(RateLimitError("429")).kind == FailureClass.API)
    check("AuthError → api", classify(AuthError("401")).kind == FailureClass.API)


async def test_recovery_suggestions() -> None:
    print("\n[6] Recovery suggestions auto-generated per failure class")
    for kind in FailureClass:
        info = classify(f"sample {kind.value} error", component="executor")
        if kind == FailureClass.UNKNOWN:
            info.kind = FailureClass.UNKNOWN
        suggestions = suggestions_for(info) if info.kind is not FailureClass.UNKNOWN \
            else suggestions_for(info)
        check(f"{kind.value} has suggestions",
              isinstance(suggestions, list) and len(suggestions) >= 1,
              str(suggestions))
    # a device failure on an android tool includes a phone hint
    dev = classify("device offline", component="executor", tool="android_open_youtube")
    sugs = suggestions_for(dev)
    check("android device failure includes phone hint",
          any("phone" in s.lower() or "adb" in s.lower() for s in sugs), str(sugs))


async def test_history_and_logs_on_failure() -> None:
    print("\n[7] Failure → history (classified) + structured log")
    app = fresh_app()
    rt = RollbackTool()
    app.registry.register(rt)
    from executor.executor import Executor
    from executor.policy import ExecutionPolicy
    executor = Executor(app.db, app.llm, app.memory, app.registry, app.observers,
                        ExecutionPolicy(), devices=app.devices)
    from core.contracts import ToolCall
    await executor._dispatch_tool("rel2", None,
                                  ToolCall(id="t2", name="reli_roll", arguments={"key": "k2"}))
    from database.models import ToolExecution
    with app.db.session() as s:
        row = s.query(ToolExecution).filter_by(tool="reli_roll").first()
    check("history has recovery_suggestions JSON",
          row is not None and row.recovery_suggestions,
          (row.recovery_suggestions or "")[:60] if row else "none")
    sugs = json.loads(row.recovery_suggestions) if row and row.recovery_suggestions else []
    check("suggestions non-empty list", isinstance(sugs, list) and len(sugs) >= 1,
          str(sugs))
    # structured log contains the classified failure
    logfile = app.config.log_dir / "agentcore.jsonl"
    raw = logfile.read_text(encoding="utf-8", errors="replace") if logfile.exists() else ""
    check("structured log has failure_class field", "failure_class" in raw
          and "reli_roll" in raw, f"log bytes={len(raw)}")


async def test_step_failure_classification() -> None:
    print("\n[8] Step-level failure classified + suggestions in Execution row")
    from observer.base import Observation, Observer

    class FakeScreen(Observer):
        """Screen verification always fails → step genuinely FAILS through the
        existing retry gate (same mechanism as the vertical-slice test)."""
        source = "screen"
        def verify(self, tool_name, args, result):
            if tool_name == "android_open_youtube":
                return [Observation(source="screen", ok=False,
                                    data={"cmd": tool_name},
                                    message="✗ verification failed: screen does not show YouTube")]
            return []

    app = fresh_app()
    app.orchestrator.ensure_session("relstep")
    app.observers._observers["screen"] = FakeScreen()
    from llm.providers import MockProvider
    mp = MockProvider()
    app.llm._factory = lambda n, k, m: mp
    mp.enqueue('[TOOL android_open_youtube {"query":"x","device_id":"adb"}]',
               '[TOOL android_open_youtube {"query":"x","device_id":"adb"}]',
               '[TOOL android_open_youtube {"query":"x","device_id":"adb"}]',
               'failed after retries')
    plan, step = await app.planner.create_plan("relstep", "Open YouTube on my phone")
    outcome = await app.executor.run_step(
        "relstep", plan, step, "Open YouTube on my phone",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step)
    check("outcome has failure_class", outcome.failure_class is not None,
          str(outcome.failure_class))
    from database.models import Execution
    with app.db.session() as s:
        row = s.query(Execution).filter_by(session_id="relstep").first()
    check("execution row failure_class", row is not None and row.failure_class,
          row.failure_class if row else "none")
    check("execution row suggestions",
          row is not None and row.recovery_suggestions,
          (row.recovery_suggestions or "")[:60] if row else "none")


def main() -> None:
    asyncio.run(test_tool_timeout())
    asyncio.run(test_tool_retry())
    asyncio.run(test_tool_rollback())
    asyncio.run(test_cancellation())
    asyncio.run(test_failure_classification())
    asyncio.run(test_recovery_suggestions())
    asyncio.run(test_history_and_logs_on_failure())
    asyncio.run(test_step_failure_classification())
    print(f"\n{'='*40}\nPASSED: {PASS}   FAILED: {FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
