"""AgentCore — observer/manager.py
ObserverManager: registry + helpers. The executor calls verify_after() after
every tool execution so the planner sees observations, not just tool outputs.
"""
from __future__ import annotations

from observer.base import Observation, Observer
from observer.observers import (AndroidObserver, ClipboardObserver,
                                FilesystemObserver, NetworkObserver,
                                ScreenObserver, SystemObserver, TimeObserver)


class ObserverManager:
    def __init__(self) -> None:
        self._observers: dict[str, Observer] = {}

    def register(self, observer: Observer) -> None:
        self._observers[observer.source] = observer

    def get(self, source: str) -> Observer | None:
        return self._observers.get(source)

    def all(self) -> list[Observer]:
        return list(self._observers.values())

    # -- used by the executor --------------------------------------------
    def verify_after(self, tool_name: str, args: dict, result: dict | None) -> list[Observation]:
        """Ask every observer whether the tool's effect actually happened."""
        out: list[Observation] = []
        for obs in self._observers.values():
            try:
                out.extend(obs.verify(tool_name, args, result))
            except Exception:  # noqa: BLE001 — observers must never break the loop
                continue
        return out

    def poll(self) -> list[Observation]:
        out: list[Observation] = []
        for obs in self._observers.values():
            try:
                out.extend(obs.poll())
            except Exception:  # noqa: BLE001
                continue
        return out


def default_observers(sandbox_root: str | None = None, android_device=None) -> ObserverManager:
    mgr = ObserverManager()
    mgr.register(FilesystemObserver(sandbox_root))
    mgr.register(TimeObserver())
    mgr.register(NetworkObserver())
    mgr.register(ClipboardObserver())
    mgr.register(SystemObserver())
    mgr.register(AndroidObserver(android_device))
    mgr.register(ScreenObserver())
    return mgr
