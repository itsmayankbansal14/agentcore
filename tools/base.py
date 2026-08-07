"""AgentCore — tools/base.py
Tool ABC + ToolResult. Tools are the ONLY way the agent executes anything;
the LLM proposes, the registry validates and dispatches.

RELIABILITY (every tool execution supports):
  - timeout   : per-tool `timeout_s` enforced via asyncio.wait_for
  - retry     : per-tool `retries` with backoff (idempotent tools retry safely)
  - rollback  : tools that can undo implement `rollback(params, ctx)`;
                the Executor calls it when the execution fails
  - cancellation : asyncio.CancelledError propagates through guarded_execute
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

from core.contracts import Permission, ToolResult, ToolSpec


class Tool(ABC):
    """A single executable capability."""
    name: str = "tool"
    description: str = ""
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    capability: str = "generic"
    permission: Permission = Permission.ALWAYS
    idempotent: bool = False

    # reliability knobs (per-tool defaults; tools override)
    timeout_s: float = 30.0
    retries: int = 0            # extra attempts after the first (0 = no retry)

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description,
                        parameters=self.parameters, capability=self.capability,
                        permission=self.permission, idempotent=self.idempotent)

    @abstractmethod
    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        """ctx carries session_id, device manager, memory, etc."""
        ...

    async def rollback(self, params: dict[str, Any], ctx: dict[str, Any]) -> None:
        """Undo a partially-applied execution. Default: no-op.
        Tools that can revert side effects override this."""
        return None

    async def guarded_execute(self, params: dict[str, Any],
                              ctx: dict[str, Any]) -> ToolResult:
        """Timeout + retry + cancellation wrapper. The Executor calls this
        (via the registry); it never needs to re-implement the loop."""
        t0 = time.time()
        attempts = 0
        last_result: ToolResult | None = None
        while True:
            attempts += 1
            try:
                result = await asyncio.wait_for(
                    self.execute(params, ctx), timeout=self.timeout_s)
            except asyncio.CancelledError:
                raise  # cancellation propagates to the executor → CANCELLED
            except asyncio.TimeoutError:
                result = ToolResult(ok=False, tool=self.name,
                                    error=f"tool timeout after {self.timeout_s}s")
            except Exception as e:  # noqa: BLE001
                result = ToolResult(ok=False, tool=self.name, error=str(e))
            result.tool = self.name
            result.duration_ms = int((time.time() - t0) * 1000)
            result.attempts = attempts
            if result.ok or attempts > self.retries:
                return result
            last_result = result
            # small backoff before retrying (idempotent tools only retry safely)
            await asyncio.sleep(min(0.5 * attempts, 2.0))
        # unreachable; keeps type checkers happy
        return last_result or ToolResult(ok=False, tool=self.name, error="retries exhausted")
