#!/usr/bin/env python3
"""AgentCore — scripts/test_live.py
Live provider tests against real APIs (Phase 4). Requires keys in .env.

Usage: python scripts/test_live.py

Tests:
  1. Direct chat via the first real provider (OpenRouter)
  2. Tool-calling loop: the real model calls time_now through the agent
  3. Live failover: a bad key first, then OpenRouter serves the same call
  4. Continuity: long-term memory recall across turns with a real LLM
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.app import AgentApp
from core.contracts import LLMMessage, Role
from llm.router import KeyRuntime

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


async def main() -> None:
    app = AgentApp.create()

    print("Configured providers:")
    real = []
    for k in app.llm.router.keys:
        has_key = bool(k.key and k.key != "mock-key")
        print(f"  - {k.provider:12s} model={k.model:28s} key={'yes' if has_key else 'no'}")
        if has_key:
            real.append(k)
    if not real:
        print("\n❌ No real API keys configured. Add OPENROUTER_API_KEY (etc.) to .env")
        sys.exit(1)

    # ---- [1] direct chat ---------------------------------------------------
    print("\n[1] Direct chat (first real provider)")
    t0 = time.time()
    resp = await app.llm.chat([LLMMessage(role=Role.USER,
                                          content="Reply with exactly: hello from agentcore")])
    ms = int((time.time() - t0) * 1000)
    print(f"  provider={resp.provider} model={resp.model} ({ms}ms)")
    check("got content", bool(resp.content), resp.content or "")
    check("served by openrouter", resp.provider == "openrouter", resp.provider)
    check("content sane", "agentcore" in (resp.content or "").lower(), resp.content or "")

    # ---- [2] tool-calling loop --------------------------------------------
    print("\n[2] Tool-calling loop (agent asks the model to use time_now)")
    out = await app.orchestrator.handle_user_message(
        "live", "What time is it right now? Use the time_now tool if you can.")
    print(f"  reply: {out[:130]}")
    with app.db.session() as s:
        from database.models import ToolExecution
        rows = s.query(ToolExecution).filter(ToolExecution.tool == "time_now").all()
    check("real model called time_now tool", len(rows) >= 1, f"rows={len(rows)}")

    # ---- [3] live failover -------------------------------------------------
    print("\n[3] Live failover: bad key first, OpenRouter second")
    bad = KeyRuntime("openai", "sk-invalid-bad-key-0000", "gpt-4o-mini")
    app.llm.router.keys.insert(0, bad)
    t0 = time.time()
    resp2 = await app.llm.chat([LLMMessage(role=Role.USER, content="Say ok")])
    ms = int((time.time() - t0) * 1000)
    print(f"  served by {resp2.provider} ({ms}ms)")
    check("failed over to openrouter", resp2.provider == "openrouter", resp2.provider)
    check("bad key cooled down", bad.cooldown_until > 0)
    check("bad key flagged failure", bad.consecutive_failures >= 1)
    app.llm.router.keys.pop(0)

    # ---- [4] continuity: LTM + context across turns ------------------------
    print("\n[4] Continuity: long-term memory recall across turns (real LLM)")
    r1 = await app.orchestrator.handle_user_message("live2",
                                                    "Remember: my favorite color is teal.")
    r2 = await app.orchestrator.handle_user_message("live2", "What is my favorite color?")
    print(f"  turn1: {r1[:90]}")
    print(f"  turn2: {r2[:130]}")
    check("recalls favorite color", "teal" in r2.lower(), r2[:160])

    print(f"\n{'=' * 40}\nPASSED: {PASS}   FAILED: {FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
