"""AgentCore — core/bus.py
In-process typed event bus. The orchestrator coordinates by subscribing to
events; components publish; nobody reaches across to call another component's
methods directly (except via the well-defined manager facades).
Kept synchronous for MVP determinism; async publish is a drop-in later.

DISCIPLINE (Phase 2 review): use events ONLY for loose coupling where the
payload genuinely has multiple consumers (e.g. UI/WS broadcast + internal
reaction). If exactly one component consumes a value, call it directly —
never route it through the bus. Examples here: memory writes are direct
calls; USER_MESSAGE_RECEIVED / TOOL_RESULT / PROVIDER_SWITCHED are broadcast
to the dashboard AND internal handlers, so they stay on the bus.
"""
from __future__ import annotations

import structlog
from collections import defaultdict
from typing import Any, Callable

from .contracts import Event, EventType

log = structlog.get_logger("agentcore.bus")


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[EventType, list[Callable[[Event], None]]] = defaultdict(list)

    def subscribe(self, event_type: EventType, handler: Callable[[Event], None]) -> None:
        self._subs[event_type].append(handler)

    def subscribe_any(self, handler: Callable[[Event], None]) -> None:
        """Subscribe to every event (audit/logging use)."""
        for et in EventType:
            self.subscribe(et, handler)

    def publish(self, event: Event) -> None:
        for handler in list(self._subs.get(event.type, [])):
            try:
                handler(event)
            except Exception:  # noqa: BLE001 — bus must never break a publisher
                log.exception("event handler failed", type=event.type.value)

    # convenience emitters
    def emit(self, type_: EventType, payload: dict[str, Any] | None = None,
             session_id: str | None = None) -> Event:
        ev = Event(type=type_, payload=payload or {}, session_id=session_id)
        self.publish(ev)
        return ev
