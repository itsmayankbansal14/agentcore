"""AgentCore — plugins/weather.py
Weather tool backed by Open-Meteo (free, no API key, real data).

The tool resolves the city via Open-Meteo geocoding and returns the CURRENT
weather from the forecast API. No fake data: if the service is unreachable
or the city is unknown, the tool returns a structured failure — it NEVER
fabricates a forecast.
"""
from __future__ import annotations

from typing import Any

from core.contracts import ToolResult
from tools.base import Tool

_GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather-interpretation codes → human description
_WMO = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "icy fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm",
}


class WeatherTool(Tool):
    name = "weather"
    description = "Get the current weather for a city (real data via Open-Meteo)."
    parameters = {"type": "object", "properties": {"city": {"type": "string"}},
                  "required": ["city"]}
    capability = "plugin.weather"
    idempotent = True

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        city = (params.get("city") or "Jaipur").strip()
        try:
            import httpx
        except Exception as e:  # noqa: BLE001
            return ToolResult(ok=False, error=f"weather: httpx unavailable — {e}")
        try:
            with httpx.Client(timeout=12.0) as client:
                geo = client.get(_GEO_URL,
                                 params={"name": city, "count": 1, "language": "en"})
                geo.raise_for_status()
                results = (geo.json() or {}).get("results") or []
                if not results:
                    return ToolResult(ok=False,
                                      error=f"weather: city '{city}' not found")
                loc = results[0]
                fc = client.get(_FORECAST_URL, params={
                    "latitude": loc["latitude"], "longitude": loc["longitude"],
                    "current_weather": "true", "timezone": "auto"})
                fc.raise_for_status()
                cw = (fc.json() or {}).get("current_weather", {})
                temp = cw.get("temperature")
                if temp is None:
                    return ToolResult(ok=False, error="weather: no current data")
                code = cw.get("weathercode", -1)
                return ToolResult(ok=True, data={
                    "city": loc.get("name", city.title()),
                    "region": (loc.get("admin1") or "") + ", "
                              + (loc.get("country") or ""),
                    "condition": _WMO.get(code, f"code {code}"),
                    "temp_c": round(temp, 1),
                    "wind_kmh": cw.get("windspeed"),
                    "observed_at": cw.get("time"),
                    "source": "open-meteo",
                })
        except Exception as e:  # noqa: BLE001
            # honest structured failure — never fabricate a forecast
            return ToolResult(ok=False,
                              error=f"weather: service unreachable — {e}")


def register(registry, ctx: dict[str, Any]) -> None:
    registry.register(WeatherTool())
