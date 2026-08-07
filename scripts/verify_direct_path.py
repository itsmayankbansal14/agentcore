"""Verify the deterministic fast-path: deterministic requests must be answered
by real tools WITHOUT the LLM. We install a mock LLM that RAISES if invoked —
any deterministic request that reaches it fails loudly.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class NoLLMAllowed(Exception):
    pass


class BombProvider:
    """Raises if the executor ever consults the LLM."""
    name = "bomb"

    async def chat(self, messages, tools=None, session_id=None, on_overflow=None):
        raise NoLLMAllowed("LLM consulted for a deterministic request!")


def main() -> int:
    from core.app import AgentApp
    from llm.router import KeyRuntime

    app = AgentApp.create(db_path=tempfile.mktemp(suffix=".db"))
    app.llm.router.keys = [KeyRuntime("mock", "mock-key", "mock-1")]
    app.llm._factory = lambda n, k, m: BombProvider()

    cases = [
        ("what time is it?", "time", "🕐 It is"),
        ("weather in Jaipur", "weather", "🌤 Weather in Jaipur"),
        ("add todo finish DSA high priority", "todo_add", "Added todo"),
        ("list my todos", "todo_list", "Todos:"),
        # clipboard: on a real desktop → "Copied"; headless → honest failure
        ("copy hello world to clipboard", "clipboard_set", "Copied"),
        ("open youtube on my phone", "android", "failed" or "offline" or "phone"),
    ]

    async def run():
        out = []
        for goal, kind, expect in cases:
            try:
                resp = await app.orchestrator.handle_user_message("direct-test", goal)
                out.append((goal, kind, expect, resp))
            except NoLLMAllowed as e:
                out.append((goal, kind, expect, f"LLM-LEAK: {e}"))
        return out

    results = asyncio.run(run())
    fails = 0
    for goal, kind, expect, resp in results:
        # clipboard on a headless box fails honestly — that IS the correct
        # outcome there (never a fake success), so accept both.
        ok = isinstance(resp, str) and expect in resp
        if kind == "clipboard_set" and not ok:
            ok = "clipboard" in resp.lower() and "failed" in resp.lower()
        if not ok:
            fails += 1
        print(f"{'PASS' if ok else 'FAIL'}  [{kind:12s}] {goal!r:45s} -> {resp[:110]!r}")
    print(f"\n{len(results) - fails}/{len(results)} direct-path checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
