"""AgentCore — devices/browser.py
BrowserDevice: the browser runtime as a device (hosted on Windows). It is
registered in the DeviceManager so Target Resolution and the dashboard see
browser availability; the actual browser tools live in tools/workflows/
(browser_workflow.py) and are gated by ToolHealth (Playwright present?)."""
from __future__ import annotations

import importlib.util
from typing import Any

from core.contracts import ToolResult
from devices.base import Device


class BrowserDevice(Device):
    name = "browser"
    platform = "browser"

    def __init__(self) -> None:
        self._online = importlib.util.find_spec("playwright") is not None

    def connect(self) -> bool:
        self._online = importlib.util.find_spec("playwright") is not None
        return self._online

    def capabilities(self) -> list[str]:
        return ["workflow.browser"]

    def health(self) -> dict[str, Any]:
        return {"online": self._online, "runtime": "chromium (playwright)",
                "detected": "playwright installed" if self._online
                            else "playwright missing"}

    async def execute(self, command: str, params: dict[str, Any]) -> ToolResult:
        # browser commands execute through the browser_workflow tools;
        # this device reports routing, not execution
        if command not in self.capabilities():
            return ToolResult(ok=False, error=f"browser cannot execute {command}")
        return ToolResult(ok=False, error="browser tools execute via workflow tools")
