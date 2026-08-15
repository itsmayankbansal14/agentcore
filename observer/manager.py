"""AgentCore — observer/manager.py
ObserverManager: registry + helpers. The executor calls verify_after() after
every tool execution so the planner sees observations, not just tool outputs.
"""
from __future__ import annotations

import structlog

from observer.base import Observation, Observer
from observer.observers import (AndroidObserver, ClipboardObserver,
                                FilesystemObserver, NetworkObserver,
                                ScreenObserver, SystemObserver, TimeObserver)
from observer.workflow_observers import register_workflow_observers

log = structlog.get_logger("agentcore.observer")


class ObserverManager:
    """Registry + helpers. The executor calls verify_after() after every
    tool execution so the planner sees observations, not just tool outputs.
    Also keeps a small ring buffer of recent observations for the runtime API."""

    def __init__(self) -> None:
        self._observers: dict[str, Observer] = {}
        self.history: list[dict] = []     # recent observations (runtime API)

    def register(self, observer: Observer) -> None:
        self._observers[observer.source] = observer

    def get(self, source: str) -> Observer | None:
        return self._observers.get(source)

    def all(self) -> list[Observer]:
        return list(self._observers.values())

    def _record(self, obs: list[Observation]) -> None:
        for o in obs:
            # internal detail stays in the structured log (developer view)
            log.debug("observation", detail=o.log_developer())
            # the history/API keeps the public message; data stays internal
            self.history.append({"source": o.source, "ok": o.ok,
                                 "message": o.message, "ts": o.ts})
        if len(self.history) > 200:
            self.history = self.history[-200:]

    def recent(self, n: int = 25) -> list[dict]:
        return self.history[-n:]

    # -- used by the executor --------------------------------------------
    def verify_after(self, tool_name: str, args: dict, result: dict | None) -> list[Observation]:
        """Ask every observer whether the tool's effect actually happened."""
        out: list[Observation] = []
        for obs in self._observers.values():
            try:
                out.extend(obs.verify(tool_name, args, result))
            except Exception:  # noqa: BLE001 — observers must never break the loop
                continue
        self._record(out)
        return out

    def poll(self) -> list[Observation]:
        out: list[Observation] = []
        for obs in self._observers.values():
            try:
                out.extend(obs.poll())
            except Exception:  # noqa: BLE001
                continue
        self._record(out)
        return out


def default_observers(sandbox_root: str | None = None, android_device=None,
                      adb_device=None, verifier=None) -> ObserverManager:
    mgr = ObserverManager()
    mgr.register(FilesystemObserver(sandbox_root))
    mgr.register(TimeObserver())
    mgr.register(NetworkObserver())
    mgr.register(ClipboardObserver())
    mgr.register(SystemObserver())
    mgr.register(AndroidObserver(android_device or adb_device))
    mgr.register(ScreenObserver(adb_device, verifier))
    register_workflow_observers(mgr, sandbox_root or "./data/sandbox")
    return mgr
