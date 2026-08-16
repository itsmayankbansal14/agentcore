"""AgentCore — observer/base.py
Observer subsystem. Monitors environmental state (filesystem, time, network,
clipboard, system, Android/ADB, screen) and produces Observations. The
executor/planner consume observations to VERIFY outcomes instead of trusting
raw tool outputs blindly.

  Tool executes → Observer.verify(tool, args, result) → observations
  Observer.poll() → periodic environmental snapshots
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Observation:
    """Separation of concerns:
      - `message` is USER-VISIBLE (shown in the dashboard timeline).
      - `data` is INTERNAL/developer detail — logged to the structured log,
        never rendered in the UI.
    """
    source: str                    # e.g. "filesystem", "time"
    ok: bool                       # True = condition satisfied
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_context(self) -> str:
        # user-visible: message only — internal data is NOT exposed to the UI
        return f"[observation:{self.source}] {'✓' if self.ok else '✗'} {self.message}"

    def log_developer(self) -> str:
        """Developer-facing detail — goes to the structured log, not the UI."""
        return (f"{self.source} ok={self.ok} data={self.data} ts={self.ts}")


class Observer(ABC):
    source: str = "base"

    def verify(self, tool_name: str, args: dict[str, Any],
               result: dict[str, Any] | None) -> list[Observation]:
        """Check that a tool's effect actually happened in the environment.
        Default: no verification (poll-only observers)."""
        return []

    def poll(self) -> list[Observation]:
        """Periodic environmental snapshot (default: none)."""
        return []
