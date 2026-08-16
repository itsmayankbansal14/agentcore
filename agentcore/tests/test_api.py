"""AgentCore — tests/test_api.py
API + WebSocket tests using FastAPI TestClient (runs the app in-process).
Run: python tests/test_api.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from api.server import create_app
from core.app import AgentApp
from llm.providers import MockProvider

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def main() -> None:
    import tempfile
    from llm.router import KeyRuntime
    app = AgentApp.create(db_path=tempfile.mktemp(suffix=".db"))
    # hermetic: mock-only, even if real keys exist in .env
    app.llm.router.keys = [KeyRuntime(provider="mock", key="mock-key", model="mock-1")]
    prov = MockProvider()
    app.llm._factory = lambda n, k, m: prov
    client = TestClient(create_app(app))

    print("\n[A] REST endpoints")
    r = client.get("/api/health")
    check("health", r.status_code == 200 and r.json()["ok"])
    r = client.get("/api/status?session_id=web")
    check("status", r.status_code == 200 and "tools_registered" in r.json())
    r = client.get("/api/tools")
    check("tools list", r.status_code == 200 and r.json()["count"] >= 5,
          str(r.json()["count"]))
    r = client.get("/api/devices")
    check("devices", r.status_code == 200 and "windows" in r.json())
    r = client.post("/api/provider/check")
    check("provider check", r.status_code == 200 and "providers" in r.json())

    print("\n[B] Chat via REST")
    prov.enqueue("[ECHO]")
    r = client.post("/api/chat", json={"message": "hello", "session_id": "api"})
    check("chat ok", r.status_code == 200 and "response" in r.json())
    check("chat has text", bool(r.json()["response"]))

    print("\n[C] Chat via SSE stream")
    prov.enqueue("[ECHO]")
    with client.stream("POST", "/api/chat/stream",
                       json={"message": "stream me", "session_id": "api"}) as s:
        body = "".join(s.iter_text())
    check("sse returned", "data:" in body and "stream me" in body, body[:120])

    print("\n[D] Plan + resume via REST")
    r = client.post("/api/plan", json={"goal": "build an app then test it",
                                       "session_id": "api"})
    check("plan created", r.status_code == 200 and "next_step" in r.json(),
          r.text[:120])
    r = client.post("/api/resume", json={"session_id": "api"})
    check("resume", r.status_code == 200 and "response" in r.json())

    print("\n[E] Memory + knowledge via REST")
    r = client.get("/api/memory/facts?session_id=api")
    check("facts endpoint", r.status_code == 200 and "facts" in r.json())
    # ingest + search
    import tempfile as _t
    note = Path(_t.mkdtemp()) / "n.md"
    note.write_text("AgentCore dashboard test document about binary search O(log n).")
    asyncio.run(app.memory.add_knowledge(str(note)))
    r = client.get("/api/knowledge/search?q=binary+search&top_k=3")
    check("knowledge search", r.status_code == 200 and r.json()["count"] >= 1,
          r.text[:120])

    print("\n[F] Dashboard page")
    r = client.get("/")
    check("dashboard html", r.status_code == 200 and "AGENTCORE" in r.text)

    print("\n[G] Dev-console panels")
    r = client.get("/api/planner?session_id=api")
    check("planner panel", r.status_code == 200 and "steps" in r.json(), r.text[:80])
    r = client.get("/api/executions?session_id=api&limit=5")
    check("executions panel", r.status_code == 200 and "executions" in r.json())
    r = client.get("/api/logs?lines=10")
    check("logs panel", r.status_code == 200 and "logs" in r.json())

    print("\n[G2] Runtime APIs (executor / observer / runtime)")
    r = client.get("/api/executor?session_id=api")
    check("executor state", r.status_code == 200 and "phase" in r.json()
          and "policy" in r.json(), r.text[:80])
    r = client.get("/api/observer?n=5")
    check("observer events", r.status_code == 200 and "observations" in r.json())
    r = client.get("/api/runtime")
    check("runtime status", r.status_code == 200 and "provider" in r.json()
          and "uptime_s" in r.json(), r.text[:80])

    print("\n[G4] Live debugging APIs (execution/live, tools/live, timeline)")
    r = client.get("/api/execution/live?session_id=api")
    check("execution/live", r.status_code == 200 and "phase" in r.json()
          and "current_step" in r.json() and "retry_count" in r.json(),
          r.text[:80])
    r = client.get("/api/tools/live")
    check("tools/live", r.status_code == 200 and "tools" in r.json()
          and "current" in r.json())
    r = client.get("/api/timeline?session_id=api&limit=50")
    check("timeline", r.status_code == 200 and "timeline" in r.json())
    # after a chat runs, the timeline must contain the real pipeline events
    prov.enqueue('[TOOL time_now {}]', 'the time was fetched')
    client.post("/api/chat", json={"message": "what time is it", "session_id": "api"})
    r = client.get("/api/timeline?session_id=api&limit=100")
    types = {e["type"] for e in r.json()["timeline"]}
    check("timeline has step_started", "step_started" in types, str(sorted(types)))
    check("timeline has tool_started+result", "tool_started" in types and "tool_result" in types,
          str(sorted(types)))
    check("timeline has observer_result", "observer_result" in types, str(sorted(types)))
    check("timeline has step_completed", "step_completed" in types, str(sorted(types)))
    r = client.get("/api/tools/live")
    tstats = {t["tool"]: t for t in r.json()["tools"]}
    check("tool monitor has time_now with stats",
          "time_now" in tstats and tstats["time_now"]["runs"] >= 1
          and tstats["time_now"]["success_rate"] == 100.0,
          str(tstats.get("time_now")))

    print("\n[G3] SSE execution stream emits progress events + final")
    prov.enqueue('[TOOL time_now {}]', 'the time was retrieved')
    with client.stream("POST", "/api/chat/stream",
                       json={"message": "what time is it", "session_id": "api"}) as s:
        body = "".join(s.iter_text())
    check("sse has final", '"type": "final"' in body, body[:120])
    check("sse has tool event", '"tool_started"' in body or '"tool_result"' in body,
          body[:200])
    check("sse has step event", '"step_completed"' in body, body[:200])

    print("\n[H] dashboard.app entry point (thin, via AgentApp)")
    from dashboard.app import create_app as dash_create_app
    dash_client = TestClient(dash_create_app(app))
    r = dash_client.get("/")
    check("dashboard/app serves console", r.status_code == 200 and "AGENTCORE" in r.text)
    prov.enqueue("[ECHO]")
    r = dash_client.post("/api/chat", json={"message": "hello", "session_id": "api"})
    check("dashboard/app chat via AgentApp", r.status_code == 200 and "response" in r.json())
    r = dash_client.get("/api/planner?session_id=api")
    check("dashboard/app planner panel", r.status_code == 200 and "steps" in r.json())
    r = dash_client.get("/api/logs?lines=5")
    check("dashboard/app logs panel", r.status_code == 200 and "logs" in r.json())

    print(f"\n{'='*40}\nPASSED: {PASS}   FAILED: {FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
