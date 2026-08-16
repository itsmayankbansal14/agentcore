"""AgentCore — runtime audit: boot the real app, enumerate every tool with its
health state, then EXECUTE each core tool and report ok/error + observations.
No mocks, no placeholders — this is the real pipeline.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from core.app import AgentApp
    app = AgentApp.create()

    print("\n=== TOOL REGISTRY AUDIT ===")
    print(f"{'name':<28} {'capability':<22} {'health'}")
    print("-" * 80)
    health = app.health.all() if hasattr(app, "health") else {}
    from tools.health import ToolHealthManager
    if not health:
        thm = ToolHealthManager()
        thm.scan(app.registry, app.devices)
        health = thm.all()
    for name in sorted(app.registry._tools):
        t = app.registry._tools[name]
        h = health.get(name, {"state": "?", "message": ""})
        flag = {"READY": "✓", "BROKEN": "✗", "UNAVAILABLE": "◐"}.get(h["state"], "?")
        print(f"{flag} {name:<27} {t.capability:<22} {h['state']:<12} {h['message']}")
    n_broken = sum(1 for h in health.values() if h["state"] == "BROKEN")
    n_unav = sum(1 for h in health.values() if h["state"] == "UNAVAILABLE")
    print(f"\nregistered={len(app.registry._tools)} broken={n_broken} unavailable={n_unav}")
    if n_broken:
        print("BROKEN TOOLS:", [t for t, h in health.items() if h["state"] == "BROKEN"])

    print("\n=== EXECUTION AUDIT (real pipeline) ===")
    async def run():
        results = []
        cases = [
            ("time_now", {}),
            ("todo_add", {"task": "audit-probe", "priority": "low"}),
            ("todo_list", {}),
            ("weather", {"city": "Jaipur"}),
            ("fs_write", {"path": "audit_probe.txt", "content": "hello audit"}),
            ("fs_read", {"path": "audit_probe.txt"}),
            ("clipboard_set", {"text": "audit-probe-clip"}),
            ("fs_delete", {"path": "audit_probe.txt"}),
        ]
        for name, params in cases:
            tool = app.registry.get(name)
            if tool is None:
                results.append((name, "NOT REGISTERED", "—"))
                continue
            try:
                res = await tool.execute(params, {"session_id": "audit"})
                ok = res.ok
                data = res.data if ok else f"error={res.error}"
                results.append((name, "OK" if ok else "FAIL", str(data)[:150]))
            except Exception as e:  # noqa: BLE001
                results.append((name, "RAISED", f"{type(e).__name__}: {e}"))
        return results

    results = asyncio.run(run())
    for name, status, detail in results:
        print(f"  {name:<16} {status:<8} {detail}")
    failed = [r for r in results if r[1] != "OK"]
    print(f"\nexecution failures: {len(failed)}")
    for r in failed:
        print("  FAIL:", r)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
