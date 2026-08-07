"""AgentCore — tools/monitor.py
Live tool monitor (dashboard "live debugging console").

Tracks per-tool runtime stats WITHOUT touching the registry's execution:
the Executor calls `mark_start`/`mark_end` around each tool execution and
the monitor keeps: busy state, last used, durations, success/failure counts.

Also maintains a small "currently running" view so the dashboard can show
exactly which tool is executing right now and for how long.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolStats:
    name: str
    runs: int = 0
    ok: int = 0
    fail: int = 0
    total_ms: float = 0.0
    last_ms: float = 0.0
    last_used: float = 0.0        # epoch ts
    last_error: str = ""
    busy: bool = False
    busy_since: float = 0.0

    def avg_ms(self) -> float:
        return round(self.total_ms / self.runs, 1) if self.runs else 0.0

    def success_rate(self) -> float:
        return round(100.0 * self.ok / self.runs, 1) if self.runs else 100.0


class ToolMonitor:
    def __init__(self) -> None:
        self._stats: dict[str, ToolStats] = {}
        self._order: list[str] = []

    def mark_start(self, name: str) -> None:
        st = self._stats.get(name)
        if st is None:
            st = ToolStats(name=name)
            self._stats[name] = st
            self._order.append(name)
        st.busy = True
        st.busy_since = time.time()

    def mark_end(self, name: str, ok: bool, duration_ms: float, error: str = "") -> None:
        st = self._stats.get(name)
        if st is None:
            st = ToolStats(name=name)
            self._stats[name] = st
            self._order.append(name)
        st.busy = False
        st.runs += 1
        if ok:
            st.ok += 1
        else:
            st.fail += 1
        st.last_ms = round(duration_ms, 1)
        st.total_ms += duration_ms
        st.last_used = time.time()
        if error:
            st.last_error = error

    def current(self) -> dict[str, Any] | None:
        """The tool running right now (if any)."""
        for name in reversed(self._order):
            st = self._stats[name]
            if st.busy:
                return {"tool": name, "since": st.busy_since,
                        "elapsed_s": round(time.time() - st.busy_since, 1)}
        return None

    def stats(self) -> list[dict[str, Any]]:
        out = []
        for name in self._order:
            st = self._stats[name]
            out.append({
                "tool": st.name,
                "state": "busy" if st.busy else "ready",
                "busy_since": st.busy_since if st.busy else None,
                "runs": st.runs,
                "last_used": st.last_used or None,
                "last_ms": st.last_ms,
                "avg_ms": st.avg_ms(),
                "success_rate": st.success_rate(),
                "last_error": st.last_error or None,
            })
        return out
