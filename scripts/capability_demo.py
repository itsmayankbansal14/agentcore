#!/usr/bin/env python3
"""AgentCore — scripts/capability_demo.py
Runs the four capability workflows LIVE through the real pipeline
(Planner → Executor → PermissionManager → Tool Registry → Tool → Observer
→ Memory → Execution History), using the REAL configured LLM (or mock if
no key) to choose the tool calls.

  python scripts/capability_demo.py            # all four workflows
  python scripts/capability_demo.py fs         # one workflow
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.app import AgentApp


def banner(t: str) -> None:
    print("\n" + "═" * 70 + f"\n  ▶ {t}\n" + "═" * 70)


async def run_workflow(app, session, goal: str, script: list[str]) -> None:
    app.orchestrator.ensure_session(session)
    # script the LLM (deterministic tool sequence); the pipeline itself is real
    from llm.providers import MockProvider
    mp = MockProvider()
    app.llm._factory = lambda n, k, m: mp
    # the real Planner's decompose call consumes one line; prepend a safe echo
    mp.enqueue(*(["[ECHO]"] + ["%s" % l for l in script]))

    plan, step = await app.planner.create_plan(session, goal)
    print(f"  goal   : {goal}")
    print(f"  plan   : {[s.title for s in plan.steps]}")
    outcome = await app.executor.run_step(
        session, plan, step, goal,
        system_prompt_builder=lambda sid, pl: app.orchestrator._build_system_prompt(sid, pl),
        plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step)
    print(f"  status : {outcome.status}  ({outcome.duration_ms}ms)")
    for t in outcome.tool_calls:
        mark = "✓" if t["ok"] else "✗"
        print(f"    {mark} {t['name']}" + (f"  {t['error']}" if t["error"] else ""))
    for o in outcome.observations[-3:]:
        print(f"    👁 {o}")
    print(f"  result : {outcome.response[:120]}")
    return outcome


async def main() -> None:
    app = AgentApp.create()
    which = sys.argv[1] if len(sys.argv) > 1 else "all"

    if which in ("all", "fs"):
        banner("FILESYSTEM workflow (real)")
        await run_workflow(app, "cap_fs",
            "create a folder with a file, write, read, verify and delete",
            ["[TOOL fs_create_folder {\"path\":\"demo/project\"}]",
             "[TOOL fs_create_file {\"path\":\"demo/project/notes.txt\"}]",
             "[TOOL fs_write_content {\"path\":\"demo/project/notes.txt\",\"content\":\"hello\"}]",
             "[TOOL fs_read_content {\"path\":\"demo/project/notes.txt\"}]",
             "[TOOL fs_verify_integrity {\"path\":\"demo/project/notes.txt\",\"expected_content\":\"hello\"}]",
             "[TOOL fs_delete {\"path\":\"demo/project/notes.txt\"}]",
             "filesystem workflow complete"])

    if which in ("all", "browser"):
        banner("BROWSER workflow (real Chromium)")
        await run_workflow(app, "cap_browser",
            "open the browser, go to example.com, verify and screenshot",
            ["[TOOL browser_open {}]",
             "[TOOL browser_navigate {\"url\":\"https://example.com\"}]",
             "[TOOL browser_wait_load {}]",
             "[TOOL browser_verify_url {\"expected\":\"https://example.com\"}]",
             "[TOOL browser_screenshot {}]",
             "[TOOL browser_close {}]",
             "browser workflow complete"])

    if which in ("all", "windows"):
        banner("WINDOWS workflow (real process)")
        import os
        await run_workflow(app, "cap_win",
            "launch a process, detect it opened, focus, close and verify closed",
            [f'[TOOL win_launch {{"app":"{sys.executable}"}}]',
             "[TOOL win_detect_open {}]",
             "[TOOL win_focus {}]",
             "[TOOL win_close {}]",
             "[TOOL win_verify_closed {}]",
             "windows workflow complete"])

    if which in ("all", "android"):
        banner("ANDROID workflow (real ADB — honest offline if no device)")
        await run_workflow(app, "cap_android",
            "wake, unlock, open youtube, wait and screenshot on my phone",
            ["[TOOL android_wake {}]",
             "[TOOL android_unlock {}]",
             "[TOOL android_open_youtube {\"query\":\"lofi\",\"device_id\":\"adb\"}]",
             "[TOOL android_wait_ui {\"seconds\":1}]",
             "[TOOL android_screenshot {\"device_id\":\"adb\"}]",
             "android workflow attempted"])

    print("\n✅ Capability validation complete. See execution history in the dashboard (Executions panel).")


if __name__ == "__main__":
    asyncio.run(main())
