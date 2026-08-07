"""AgentCore — api/server.py
FastAPI control surface. The dashboard (and later the Android companion)
talk to the agent ONLY through this layer — never by importing the
orchestrator directly (design §5: Dashboard → REST/WebSocket → Backend → Agent).

REST:
  GET  /api/health
  GET  /api/status?session_id=
  POST /api/chat            {message, session_id}
  POST /api/chat/stream     SSE (single-event MVP; token streaming later)
  POST /api/resume          {session_id}
  POST /api/plan            {session_id, goal}
  GET  /api/tools
  GET  /api/devices
  GET  /api/memory/facts?session_id=
  GET  /api/knowledge/search?q=&top_k=
  POST /api/knowledge/ingest {path}
  POST /api/provider/check   (Phase 4 groundwork)

WS:   /ws                   chat + live event broadcast (dashboard & Android)

UI:   /                     → ui/dashboard.html
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.app import AgentApp
from core.contracts import EventType

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# request models
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    session_id: str = "web"


class PlanRequest(BaseModel):
    goal: str
    session_id: str = "web"


class ResumeRequest(BaseModel):
    session_id: str = "web"


class IngestRequest(BaseModel):
    path: str


class SearchRequest(BaseModel):
    q: str
    top_k: int = 5


class FactsRequest(BaseModel):
    session_id: str = "web"


# ---------------------------------------------------------------------------
# app factory
# ---------------------------------------------------------------------------
_START_TIME = time.time()


def create_app(agent: AgentApp | None = None, template: Path | None = None) -> FastAPI:
    app = FastAPI(title="AgentCore API", version="0.1.0")
    agent_app = agent or AgentApp.create()

    from api.ws import WSBroadcaster
    broadcaster = WSBroadcaster()
    app.state.broadcaster = broadcaster   # runtime API reads WS client count

    @app.on_event("startup")
    async def _startup() -> None:
        broadcaster.attach_loop(asyncio.get_running_loop())
        agent_app.bus.subscribe_any(broadcaster.on_event)

    # -------------------------------------------------------------- REST
    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "ts": time.time()}

    @app.get("/api/status")
    async def status(session_id: str = "web") -> dict:
        return agent_app.orchestrator.status(session_id)

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> dict:
        t0 = time.time()
        response = await agent_app.orchestrator.handle_user_message(
            req.session_id, req.message)
        return {"response": response, "ms": int((time.time() - t0) * 1000),
                "session_id": req.session_id}

    @app.post("/api/chat/stream")
    async def chat_stream(req: ChatRequest) -> StreamingResponse:
        """SSE execution stream: emits live runtime events (tool started/result,
        step completed/failed, provider switched) then the final answer.
        Reusable by the dashboard, future desktop UI, voice, and Android."""
        _WATCH = {EventType.TOOL_STARTED, EventType.TOOL_RESULT,
                  EventType.STEP_COMPLETED, EventType.STEP_FAILED,
                  EventType.PROVIDER_SWITCHED, EventType.PROVIDER_FAILED,
                  EventType.USER_MESSAGE_RECEIVED}

        async def gen():
            q: asyncio.Queue = asyncio.Queue()

            def hook(ev):
                try:
                    if ev.session_id == req.session_id or ev.session_id is None:
                        q.put_nowait(ev)
                except Exception:  # noqa: BLE001
                    pass
            agent_app.bus.subscribe_any(hook)
            task = asyncio.create_task(
                agent_app.orchestrator.handle_user_message(req.session_id, req.message))

            def sse(ev):
                return (f"data: {json.dumps({'type': 'event', 'event': ev.type.value,
                                             **ev.to_log()})}\n\n")

            try:
                while True:
                    # drain queued events, then final when the task finishes
                    while not q.empty():
                        ev = q.get_nowait()
                        if ev.type in _WATCH:
                            yield sse(ev)
                    if task.done():
                        break
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=0.25)
                        if ev.type in _WATCH:
                            yield sse(ev)
                    except asyncio.TimeoutError:
                        continue
                text = task.result()
            except Exception as e:  # noqa: BLE001
                text = f"error: {e}"
            yield f"data: {json.dumps({'type': 'final', 'text': text})}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @app.post("/api/resume")
    async def resume(req: ResumeRequest) -> dict:
        response = await agent_app.orchestrator.resume(req.session_id)
        return {"response": response}

    @app.post("/api/plan")
    async def plan(req: PlanRequest) -> dict:
        plan, step = await agent_app.planner.create_plan(req.session_id, req.goal)
        return {"plan": agent_app.planner.plan_summary(plan),
                "next_step": step.title if step else None}

    @app.get("/api/tools")
    async def tools() -> dict:
        return {"tools": [t.name for t in sorted(agent_app.registry._tools.values(),
                                                 key=lambda t: t.name)],
                "count": len(agent_app.registry)}

    @app.get("/api/tools/live")
    async def tools_live() -> dict:
        """Live tool monitor: state (ready/busy), last used, exec time, success rate."""
        return {"tools": agent_app.tool_monitor.stats(),
                "current": agent_app.tool_monitor.current()}

    @app.get("/api/tools/health")
    async def tools_health() -> dict:
        """Tool health: READY / BROKEN / UNAVAILABLE / BUSY + install hints.
        BROKEN tools are detected at startup (e.g. missing Playwright)."""
        health = agent_app.tool_health.all()
        monitor = {t["tool"]: t for t in agent_app.tool_monitor.stats()}
        out = {}
        for name, h in health.items():
            state = h["state"]
            m = monitor.get(name)
            if m and m["state"] == "busy":
                state = "BUSY"
            out[name] = {"state": state, "message": h["message"],
                         "install_hint": h["install_hint"],
                         "recovery_attempts": (m or {}).get("recovery_attempts", 0),
                         "recovery_success": (m or {}).get("recovery_success", 0)}
        return {"tools": out,
                "broken": [n for n, h in out.items() if h["state"] == "BROKEN"]}

    @app.get("/api/execution/live")
    async def execution_live(session_id: str = "web") -> dict:
        """Live execution state: current goal / plan / step / running tool /
        retry count / elapsed time — the dashboard's live-execution panel."""
        plan = agent_app.planner.get_active_plan(session_id)
        wm = agent_app.memory.load_working(session_id)
        phase = "idle"
        goal = wm.get("current_task") or ""
        plan_s = agent_app.planner.plan_summary(plan) if plan else None
        step = None
        running_tool = agent_app.tool_monitor.current()
        retries = 0
        started_at = None
        if plan is not None:
            for st in plan.steps:
                if st.status in ("RUNNING", "WAITING_TOOL", "OBSERVING", "RETRYING", "PLANNING"):
                    phase = "executing"
                    step = {"title": st.title, "status": st.status,
                            "attempts": st.attempts, "order": st.order_idx}
                    retries = max(0, st.attempts - 1)
                    break
        elapsed = None
        if phase == "executing" and running_tool:
            elapsed = running_tool.get("elapsed_s")
        return {
            "phase": phase,
            "goal": goal[:160],
            "plan": plan_s,
            "current_step": step,
            "running_tool": running_tool,
            "retry_count": retries,
            "started_at": started_at,
            "elapsed_s": elapsed,
            "session": session_id,
        }

    @app.get("/api/timeline")
    async def timeline(session_id: str = "web", limit: int = 100) -> dict:
        """Complete execution timeline for a session (event bus history)."""
        events = agent_app.bus.recent(session_id=session_id, n=limit)
        return {"timeline": [e.to_log() for e in events]}

    @app.get("/api/devices")
    async def devices() -> dict:
        out = {}
        for d in agent_app.devices.all():
            h = d.health()
            out[d.name] = {**h, "capabilities": d.capabilities()}
        return out

    @app.post("/api/devices/pair")
    async def devices_pair() -> dict:
        """Start pairing: returns a one-time 6-digit code the phone app uses."""
        android = agent_app.devices.get("android")
        if android is None:
            return {"error": "android device not configured"}, 400
        return android.start_pairing()

    @app.get("/api/devices/android/status")
    async def android_status() -> dict:
        android = agent_app.devices.get("android")
        if android is None:
            return {"error": "android not configured"}, 400
        return android.health()

    # -------------------------------------------------------------- WS (phone)
    @app.websocket("/ws/android")
    async def ws_android(ws: WebSocket) -> None:
        """Phone companion endpoint — the device connects HERE (laptop is server)."""
        await ws.accept()
        android = agent_app.devices.get("android")
        if android is None:
            await ws.close(code=1011, reason="android device not configured")
            return
        try:
            ok = await android.attach(ws)
            if not ok:
                return  # attach closed the socket (already connected)
            # keep the task alive; attach() spawned its own receive loop
            while True:
                await asyncio.sleep(3600)
        except Exception:  # noqa: BLE001
            pass
        finally:
            # only tear down if THIS socket is still the active device link —
            # a rejected duplicate must not disconnect the real phone.
            if getattr(android, "_ws", None) is ws:
                android.disconnect()

    @app.get("/api/memory/facts")
    async def facts(session_id: str = "web") -> dict:
        return {"facts": agent_app.memory.recall(session_id, top_k=50)}

    @app.get("/api/knowledge/search")
    async def knowledge_search(q: str = "", top_k: int = 5) -> dict:
        hits = await agent_app.memory.search_knowledge(q, top_k=top_k)
        return {"query": q, "hits": hits, "count": len(hits)}

    @app.post("/api/knowledge/ingest")
    async def knowledge_ingest(req: IngestRequest) -> dict:
        p = Path(req.path).resolve()
        if p.is_dir():
            return await agent_app.memory.add_knowledge_dir(str(p))
        return await agent_app.memory.add_knowledge(str(p))

    @app.post("/api/provider/check")
    async def provider_check() -> dict:
        """Phase 4 groundwork: report configured providers/keys + health state."""
        rows = []
        for key in agent_app.llm.router.keys:
            rows.append({
                "provider": key.provider,
                "model": key.model,
                "key_configured": bool(key.key and key.key != "mock-key"),
                "consecutive_failures": key.consecutive_failures,
                "in_cooldown": key.cooldown_until > time.time(),
            })
        return {"providers": rows,
                "priority": agent_app.config.get_list("llm.provider_priority", [])}

    # -------------------------------------------------------------- WS
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        broadcaster.add(ws)
        try:
            while True:
                data = await ws.receive_json()
                kind = data.get("type", "ping")
                if kind == "chat":
                    sid = data.get("session_id", "web")
                    msg = data.get("message", "")
                    if msg.strip():
                        resp = await agent_app.orchestrator.handle_user_message(sid, msg)
                        await ws.send_json({"type": "reply", "message": msg,
                                            "response": resp, "session_id": sid})
                elif kind == "ping":
                    await ws.send_json({"type": "pong", "ts": time.time()})
                elif kind == "status":
                    await ws.send_json({"type": "status",
                                        "data": agent_app.orchestrator.status(
                                            data.get("session_id", "web"))})
                else:
                    await ws.send_json({"type": "error", "detail": f"unknown type {kind}"})
        except WebSocketDisconnect:
            broadcaster.remove(ws)
        except Exception as e:  # noqa: BLE001
            broadcaster.remove(ws)
            try:
                await ws.send_json({"type": "error", "detail": str(e)})
            except Exception:
                pass

    # -------------------------------------------------------------- dev-console data
    @app.get("/api/planner")
    async def planner_status(session_id: str = "web") -> dict:
        """Active plan + step statuses (dashboard Planner panel)."""
        plan = agent_app.planner.get_active_plan(session_id)
        if plan is None:
            return {"plan": None, "goal": None, "status": None, "steps": []}
        return {
            "plan": agent_app.planner.plan_summary(plan),
            "goal": plan.goal,
            "status": plan.status,
            "steps": [{"title": st.title, "status": st.status, "order": st.order_idx}
                      for st in plan.steps],
        }

    @app.get("/api/executions")
    async def executions(session_id: str = "web", limit: int = 12) -> dict:
        """Recent execution history (dashboard Execution panel) + token/cost totals."""
        from database.models import Execution
        with agent_app.db.session() as s:
            rows = (s.query(Execution).filter_by(session_id=session_id)
                    .order_by(Execution.id.desc()).limit(min(limit, 50)).all())
            total_tokens = sum((r.tokens_in or 0) + (r.tokens_out or 0) for r in rows)
            total_cost = sum(r.cost or 0.0 for r in rows)
            return {"executions": [{
                "id": r.id, "goal": (r.goal or "")[:80], "status": r.status,
                "duration_ms": r.duration_ms,
                "tokens": (r.tokens_in or 0) + (r.tokens_out or 0),
                "cost": round(r.cost or 0.0, 4),
                "started": (r.started_at or "")[:19],
                "failure_class": r.failure_class,
                "recovery_suggestions": (json.loads(r.recovery_suggestions)
                                         if r.recovery_suggestions else []),
            } for r in rows],
                "total_tokens": total_tokens,
                "total_cost": round(total_cost, 4)}

    @app.get("/api/executor")
    async def executor_state(session_id: str = "web") -> dict:
        """Executor state: phase (idle/executing), active step, policy budgets."""
        policy = agent_app.executor.policy
        plan = agent_app.planner.get_active_plan(session_id)
        phase = "idle"
        active = None
        if plan is not None:
            for st in plan.steps:
                if st.status in ("RUNNING", "WAITING_TOOL", "OBSERVING",
                                 "RETRYING", "PLANNING"):
                    phase = "executing"
                    active = {"title": st.title, "status": st.status, "order": st.order_idx}
                    break
        return {
            "phase": phase,
            "active_step": active,
            "policy": {
                "max_runtime_s": policy.max_runtime_s,
                "max_steps": policy.max_steps,
                "max_tokens": policy.max_tokens,
                "max_cost": policy.max_cost,
                "max_retries": policy.max_retries,
                "step_timeout_s": policy.step_timeout_s,
            },
        }

    @app.get("/api/observer")
    async def observer_state(n: int = 20) -> dict:
        """Recent observer observations (dashboard Observer panel)."""
        return {"observations": agent_app.observers.recent(min(n, 100))}

    @app.get("/api/runtime")
    async def runtime_status() -> dict:
        """Runtime identity/health — the SAME AgentApp serves every interface."""
        keys = agent_app.llm.router.healthy_keys()
        provider = keys[0].provider if keys else "none"
        model = keys[0].model if keys else ""
        ws_clients = 0
        try:
            ws_clients = app.state.broadcaster.clients()
        except Exception:  # noqa: BLE001
            pass
        return {
            "name": "AgentCore Runtime",
            "version": "0.1.0",
            "provider": provider,
            "model": model,
            "uptime_s": round(time.time() - _START_TIME, 1),
            "tools": len(agent_app.registry),
            "devices": {d.name: d.health().get("online") for d in agent_app.devices.all()},
            "ws_clients": ws_clients,
            "db": str(agent_app.db.path),
            "log_dir": str(agent_app.config.log_dir),
        }

    @app.get("/api/screenshots")
    async def screenshots(limit: int = 10) -> dict:
        """List captured device screenshots (vertical slice verification)."""
        shots_dir = agent_app.config.data_dir / "screenshots"
        if not shots_dir.exists():
            return {"screenshots": []}
        files = sorted(shots_dir.glob("*.png"), key=lambda p: p.stat().st_mtime,
                       reverse=True)[:min(limit, 50)]
        return {"screenshots": [{"name": p.name, "url": f"/api/screenshots/{p.name}",
                                 "size": p.stat().st_size,
                                 "ts": p.stat().st_mtime} for p in files]}

    @app.get("/api/screenshots/{name}")
    async def screenshot_file(name: str):
        from fastapi.responses import FileResponse
        shots_dir = agent_app.config.data_dir / "screenshots"
        p = shots_dir / name
        if not p.exists() or p.suffix.lower() != ".png":
            return {"error": "not found"}, 404
        return FileResponse(p, media_type="image/png")

    @app.get("/api/logs")
    async def logs(lines: int = 30) -> dict:
        """Tail of the structured JSONL log (dashboard Logs panel)."""
        log_file = agent_app.config.log_dir / "agentcore.jsonl"
        if not log_file.exists():
            return {"logs": []}
        raw = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"logs": raw[-min(lines, 200):]}

    # -------------------------------------------------------------- UI
    ui_file = template or ROOT / "ui" / "dashboard.html"
    if ui_file.exists():
        dashboard_html = ui_file.read_text(encoding="utf-8")

        @app.get("/", response_class=HTMLResponse)
        async def index() -> str:
            return dashboard_html
    else:
        @app.get("/", response_class=HTMLResponse)
        async def index() -> str:
            return "<h1>AgentCore</h1><p>ui/dashboard.html missing</p>"

    return app
