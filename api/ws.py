"""AgentCore — api/ws.py
WebSocket broadcaster. Subscribes to the agent's event bus and forwards events
to connected clients (dashboard UI now, Android companion in Phase 5 — the
same /ws endpoint serves both).

The bus handler is sync, so we schedule the async sends onto the running loop.
"""
from __future__ import annotations

import asyncio
import logging

import structlog

from core.contracts import Event

log = structlog.get_logger("agentcore.api.ws")


class WSBroadcaster:
    def __init__(self) -> None:
        self._sockets: set = set()   # of starlette.websockets.WebSocket
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def add(self, ws) -> None:
        self._sockets.add(ws)
        log.info("ws client connected", clients=len(self._sockets))

    def remove(self, ws) -> None:
        self._sockets.discard(ws)
        log.info("ws client disconnected", clients=len(self._sockets))

    def on_event(self, event: Event) -> None:
        """Synchronous bus-handler → schedule async broadcast."""
        if not self._sockets or self._loop is None or not self._loop.is_running():
            return
        try:
            self._loop.create_task(self._broadcast(event))
        except RuntimeError:
            pass

    async def _broadcast(self, event: Event) -> None:
        payload = event.to_log()
        dead = []
        for ws in list(self._sockets):
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.remove(ws)

    def clients(self) -> int:
        return len(self._sockets)
