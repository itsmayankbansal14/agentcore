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
    source: str                    # e.g. "filesystem", "time"
    ok: bool                       # True = condition satisfied
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_context(self) -> str:
        return f"[observation:{self.source}] {'✓' if self.ok else '✗'} {self.message} {self.data}"


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
