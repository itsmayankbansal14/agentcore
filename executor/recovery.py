"""AgentCore — executor/recovery.py
RecoveryPolicy — self-healing execution.

When a tool fails with a RECOVERABLE failure:

    Tool
      ↓
    RecoveryPolicy.is_recoverable(failure)
      ↓
    RecoveryPolicy.repair(failure, tool, services)   (init storage, reconnect device, …)
      ↓
    Retry the tool
      ↓
    Observer verification (validates the retry actually worked)

The Executor integrates this around tool dispatch (no redesign — the policy
is a new seam). Recovery attempts/success are recorded per tool (dashboard).

Repairs implemented:
  - todo_storage_init : initialize todo storage, then retry the todo tool
  - device_reconnect  : try reconnecting the adb/device transport
  - wait_cooldown     : sleep briefly for rate-limited APIs
  - noop              : plain retry (transient network/device)
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import structlog

from core.errors import FailureClass, FailureInfo

log = structlog.get_logger("agentcore.recovery")


@dataclass
class RepairResult:
    ok: bool
    action: str = ""
    detail: str = ""
    wait_s: float = 0.0


@dataclass
class RecoveryStats:
    attempts: int = 0
    successes: int = 0
    last_action: str = ""


class RecoveryPolicy:
    """Decides recoverability, performs repairs, and gates retries."""

    def __init__(self, max_recovery_attempts: int = 2,
                 cooldown_s: float = 1.0) -> None:
        self.max_attempts = max_recovery_attempts
        self.cooldown_s = cooldown_s
        self.stats: dict[str, RecoveryStats] = {}

    # -- decisions -----------------------------------------------------------
    def is_recoverable(self, info: FailureInfo) -> bool:
        return bool(info.recoverable)

    def should_retry(self, tool: str, attempt: int) -> bool:
        return attempt <= self.max_attempts

    # -- per-tool stats ------------------------------------------------------
    def _stats(self, tool: str) -> RecoveryStats:
        return self.stats.setdefault(tool, RecoveryStats())

    def record_attempt(self, tool: str, action: str) -> None:
        s = self._stats(tool)
        s.attempts += 1
        s.last_action = action

    def record_success(self, tool: str) -> None:
        s = self._stats(tool)
        s.successes += 1

    def summary(self) -> dict[str, dict]:
        return {t: {"attempts": s.attempts, "successes": s.successes,
                    "last_action": s.last_action}
                for t, s in self.stats.items()}

    # -- repairs -------------------------------------------------------------
    async def repair(self, info: FailureInfo, tool: str,
                     services: dict[str, Any]) -> RepairResult:
        """Perform the appropriate repair for the failure. Returns a result;
        the caller then retries the tool if repair ok."""
        low = info.detail.lower()
        # 1) todo storage missing → initialize the storage
        if tool.startswith("todo_") or any(s in low for s in
                                           ("storage", "no such table", "not initialized")):
            provider = services.get("todo_storage_provider")
            if provider is not None:
                try:
                    provider.storage().ensure_initialized()
                    self.record_attempt(tool, "todo_storage_init")
                    log.info("repaired: todo storage initialized", tool=tool)
                    return RepairResult(ok=True, action="todo_storage_init",
                                        detail="todo storage initialized")
                except Exception as e:  # noqa: BLE001
                    return RepairResult(ok=False, action="todo_storage_init",
                                        detail=str(e)[:120])

        # 2) device offline → try reconnecting the adb/device transport
        if info.kind == FailureClass.DEVICE:
            dev = services.get("devices")
            if dev is not None:
                adb = dev.get("adb")
                if adb is not None and not adb.health().get("online"):
                    try:
                        adb.connect()   # real reconnect attempt
                        self.record_attempt(tool, "device_reconnect")
                        ok = adb.health().get("online")
                        log.info("device reconnect attempted", tool=tool, ok=ok)
                        return RepairResult(ok=ok, action="device_reconnect",
                                            detail=f"adb reconnect -> online={ok}")
                    except Exception as e:  # noqa: BLE001
                        return RepairResult(ok=False, action="device_reconnect",
                                            detail=str(e)[:120])

        # 3) rate-limited API → wait a cooldown before retrying
        if info.kind == FailureClass.API and "rate" in low:
            self.record_attempt(tool, "wait_cooldown")
            await asyncio.sleep(self.cooldown_s)
            return RepairResult(ok=True, action="wait_cooldown",
                                detail=f"waited {self.cooldown_s}s", wait_s=self.cooldown_s)

        # 4) default: plain retry (transient)
        self.record_attempt(tool, "noop")
        return RepairResult(ok=True, action="noop", detail="retry without repair")
