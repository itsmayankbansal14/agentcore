"""AgentCore — tools/local/echo.py
Minimal demonstration tools: clock + echo. Useful for loop tests.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from core.contracts import ToolResult
from tools.base import Tool


class GetTimeTool(Tool):
    name = "time_now"
    description = "Get the current date and time (Asia/Calcutta)."
    parameters = {"type": "object", "properties": {}}
    capability = "generic"
    idempotent = True

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        now = datetime.now().strftime("%A, %d %B %Y, %I:%M %p")
        return ToolResult(ok=True, data={"now": now})


class EchoTool(Tool):
    name = "echo"
    description = "Echo back the provided text (used for testing the loop)."
    parameters = {"type": "object", "properties": {"text": {"type": "string"}},
                  "required": ["text"]}
    capability = "generic"
    idempotent = True

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, data={"echo": params.get("text", "")})


def register_all(registry) -> None:
    registry.register(GetTimeTool())
    registry.register(EchoTool())
