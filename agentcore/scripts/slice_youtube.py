#!/usr/bin/env python3
"""AgentCore — scripts/slice_youtube.py
The complete vertical slice, run live:

    "Open YouTube on an Android phone"
    User goal → Planner creates a plan → Executor executes →
    Android device manager sends REAL ADB commands → Observer captures the
    screen → Vision verification (LLM/OCR/pixel) confirms YouTube opened →
    Executor reports success or retries → Memory stores the completed task →
    Execution history records everything.

No mocks: it uses the same AgentApp runtime as the dashboard/CLI. You need a
real Android device/emulator reachable via adb (emulator on :5555, or
`adb connect <ip>:5555`). Watch the same flow live in the dashboard
(/api/observer, /api/screenshots, /api/executions, WS event feed).

Usage:
  python scripts/slice_youtube.py                 # full live slice (needs a device)
  python scripts/slice_youtube.py --verify-only <screenshot.png>   # verification only
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.app import AgentApp


def banner(text: str) -> None:
    print("\n" + "═" * 66 + f"\n  ▶ {text}\n" + "═" * 66)


async def main() -> None:
    args = sys.argv[1:]
    app = AgentApp.create()
    session = "slice_live"

    # ---- verification-only mode (no device needed) -------------------------
    if args and args[0] == "--verify-only":
        from vision.verifier import VisionVerifier
        path = args[1]
        verifier = VisionVerifier(llm=app.llm, ocr=True)
        v = await verifier.verify("youtube", path)
        print(f"VERIFY {path}\n  ok={v.ok}  engine={v.engine}\n  reason: {v.reason}")
        sys.exit(0 if v.ok else 1)

    adb = app.devices.get("adb")
    print("GOAL        : Open YouTube on an Android phone")
    print(f"ADB device  : {adb.host}:{adb.port}  online={adb.health()['online']}")
    if not adb.health()["online"]:
        print("\n❌ No adb device reachable. Start an emulator or run:\n"
              "     adb connect <phone-ip>:5555\n   then re-run this script.")
        sys.exit(2)

    # ---- 1. Planner creates the plan ---------------------------------------
    banner("1. PLANNER — decompose goal")
    app.orchestrator.ensure_session(session)
    plan, step = await app.planner.create_plan(session, "Open YouTube on my Android phone")
    print(app.planner.plan_summary(plan))
    print(f"▶ first step: {step.title}")

    # ---- 2. Executor executes the step -------------------------------------
    banner("2. EXECUTOR — run step (REAL adb command + screen verification)")
    outcome = await app.executor.run_step(
        session, plan, step, "Open YouTube on my Android phone",
        system_prompt_builder=lambda sid, pl: app.orchestrator._build_system_prompt(sid, pl),
        plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step)

    print(f"\nSTATUS    : {outcome.status}")
    print(f"TOOL CALLS: {outcome.tool_calls}")
    print(f"BUDGET    : {outcome.budget}")
    for o in outcome.observations:
        print("OBS       :", o)
    print(f"RESPONSE  : {outcome.response[:200]}")

    # ---- 3. Execution history ----------------------------------------------
    banner("3. EXECUTION HISTORY")
    from database.models import Execution, ToolExecution
    with app.db.session() as s:
        ex = s.query(Execution).filter_by(session_id=session).first()
        tools = s.query(ToolExecution).filter_by(session_id=session).all()
    print(f"execution : status={ex.status if ex else '?'} goal={ex.goal[:50] if ex else ''} "
          f"tokens={ex.tokens_in + ex.tokens_out if ex else 0} cost=${ex.cost if ex else 0}")
    for t in tools:
        print(f"tool      : {t.tool} status={t.status} err={(t.error or '')[:60]}")

    # ---- 4. Memory ----------------------------------------------------------
    banner("4. MEMORY")
    wm = app.memory.load_working(session)
    print("working   :", wm.get("current_task"))
    print("facts     :", [f for f in app.memory.recall(session, top_k=5)])

    print("\n✅ SLICE COMPLETE — status:", outcome.status)
    sys.exit(0 if outcome.status == "DONE" else 1)


if __name__ == "__main__":
    asyncio.run(main())
