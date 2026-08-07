"""AgentCore — tools/base.py
Tool ABC + ToolResult. Tools are the ONLY way the agent executes anything;
the LLM proposes, the registry validates and dispatches.
"""
from __future__ import annotations

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

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description,
                        parameters=self.parameters, capability=self.capability,
                        permission=self.permission, idempotent=self.idempotent)

    @abstractmethod
    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        """ctx carries session_id, device manager, memory, etc."""
        ...

    async def guarded_execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        t0 = time.time()
        try:
            result = await self.execute(params, ctx)
        except Exception as e:  # noqa: BLE001
            result = ToolResult(ok=False, error=str(e), tool=self.name)
        result.tool = self.name
        result.duration_ms = int((time.time() - t0) * 1000)
        return result
