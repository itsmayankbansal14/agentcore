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
def create_app(agent: AgentApp | None = None) -> FastAPI:
    app = FastAPI(title="AgentCore API", version="0.1.0")
    agent_app = agent or AgentApp.create()

    from api.ws import WSBroadcaster
    broadcaster = WSBroadcaster()

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
        async def gen():
            # SSE: one data event per chunk (MVP), keepalive comment
            response = await agent_app.orchestrator.handle_user_message(
                req.session_id, req.message)
            yield f"data: {json.dumps({'type': 'final', 'text': response})}\n\n"
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

    @app.get("/api/devices")
    async def devices() -> dict:
        return {d.name: d.health() for d in agent_app.devices.all()}

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

    # -------------------------------------------------------------- UI
    ui_file = ROOT / "ui" / "dashboard.html"
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
