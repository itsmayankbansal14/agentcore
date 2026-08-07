"""AgentCore — devices/windows.py
WindowsDevice: the local laptop as a device. Executes capability-targeted
commands by dispatching into the local tool registry (filesystem, shell,
browser later). This makes "control my laptop" and "control my phone" the
same conceptual operation.
"""
from __future__ import annotations

import platform
from typing import Any

from core.contracts import ToolResult
from tools.registry import ToolRegistry
from devices.base import Device


class WindowsDevice(Device):
    name = "windows"
    platform = "windows"

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._online = True

    def connect(self) -> bool:
        self._online = True
        return True

    def capabilities(self) -> list[str]:
        return ["fs_read", "fs_write", "fs_list", "time_now", "echo"]

    def health(self) -> dict[str, Any]:
        return {"online": self._online, "platform": platform.system()}

    async def execute(self, command: str, params: dict[str, Any]) -> ToolResult:
        """command like 'fs_read' or 'time_now' → local registry tool."""
        tool = self.registry.get(command)
        if tool is None:
            return ToolResult(ok=False, error=f"windows cannot execute {command}")
        return await tool.guarded_execute(params, ctx={})
