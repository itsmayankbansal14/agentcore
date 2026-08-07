"""AgentCore — tools/health.py
ToolHealthManager — dependency + availability health for every tool.

States:
  READY        dependency present, usable
  BROKEN       a required dependency is missing (e.g. Playwright) — the tool
               will NOT execute; installation instructions are attached
  UNAVAILABLE  dependency present but a runtime prerequisite is not
               (e.g. adb device offline) — the tool degrades honestly
  BUSY         currently executing (from the ToolMonitor)

`scan(registry, devices)` runs at startup so BROKEN tools are detected BEFORE
execution. The dashboard exposes this via /api/tools/health.
"""
from __future__ import annotations

import importlib.util
import shutil
from typing import Any

import structlog

log = structlog.get_logger("agentcore.health")


def _importable(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


# capability-family → health check: (state, message, install_hint)
_FAMILY_CHECKS = {
    "workflow.browser": lambda: (
        ("BROKEN", "Playwright is not installed",
         "pip install playwright && python -m playwright install chromium")
        if not (_importable("playwright") and _importable("playwright.async_api"))
        else ("READY", "Playwright + Chromium available", "")),
    "device.android": None,   # resolved per-device (adb/ws) below
    "workflow.android": None,
}


class ToolHealthManager:
    def __init__(self) -> None:
        self._health: dict[str, dict[str, str]] = {}

    def scan(self, registry, devices) -> None:
        """Evaluate health for every registered tool at startup."""
        for tool in registry._tools.values():
            state, message, hint = "READY", "ok", ""
            cap = getattr(tool, "capability", "")
            if cap in _FAMILY_CHECKS and _FAMILY_CHECKS[cap] is not None:
                state, message, hint = _FAMILY_CHECKS[cap]()
            elif cap in ("device.android", "workflow.android"):
                # device-dependent: adb or ws companion must be online
                adb = devices.get("adb") if devices else None
                wsdev = devices.get("android") if devices else None
                adb_ok = adb is not None and adb.health().get("online")
                ws_ok = wsdev is not None and wsdev.health().get("online")
                if adb_ok or ws_ok:
                    state, message = "READY", "device connected"
                else:
                    state, message = "UNAVAILABLE", "no android device connected"
                    hint = ("Connect a device: adb connect <ip>:5555, or pair the "
                            "companion app (POST /api/devices/pair)")
            self._health[tool.name] = {"state": state, "message": message,
                                       "install_hint": hint}
            if state != "READY":
                log.warning("tool health", tool=tool.name, state=state,
                            message=message)

    def state(self, tool: str) -> dict[str, str]:
        return self._health.get(tool, {"state": "READY", "message": "ok",
                                       "install_hint": ""})

    def all(self) -> dict[str, dict[str, str]]:
        return dict(self._health)

    def broken(self) -> list[str]:
        return [t for t, h in self._health.items() if h["state"] == "BROKEN"]
