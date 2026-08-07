"""AgentCore — plugins/weather.py
Sample plugin: adds a `weather` tool that returns a mock forecast.
Copy this file pattern to add your own capabilities without touching the core.

To use: restart the runtime — the plugin manager auto-discovers this module
and registers the tool.
"""
from __future__ import annotations

import random
from typing import Any

from core.contracts import ToolResult
from tools.base import Tool


class WeatherTool(Tool):
    name = "weather"
    description = "Get the current weather for a city (sample plugin — mock data)."
    parameters = {"type": "object", "properties": {"city": {"type": "string"}},
                  "required": ["city"]}
    capability = "plugin.weather"
    idempotent = True

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        city = params.get("city", "Jaipur")
        cond = random.choice(["clear", "partly cloudy", "rainy", "sunny"])
        temp = random.randint(18, 38)
        return ToolResult(ok=True, data={
            "city": city, "condition": cond, "temp_c": temp,
            "note": "mock data from sample plugin",
        })


def register(registry, ctx: dict[str, Any]) -> None:
    registry.register(WeatherTool())
