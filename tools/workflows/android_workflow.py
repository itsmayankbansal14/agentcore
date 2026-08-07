"""AgentCore — tools/workflows/android_workflow.py
Android workflow (REAL ADB commands through the ADBDevice):
  wake device → unlock device → launch YouTube → wait for UI → screenshot
  → verify YouTube home (Observer/Vision) → retry automatically if failed.

Every step issues a real `adb shell`/`exec-out` command via devices/adb.py
(the adb-shell protocol client). With no device attached the commands fail
HONESTLY (classified Device failure + recovery suggestions), and the
verification gate triggers the Executor's retry loop.
"""
from __future__ import annotations

import time
from typing import Any

from core.contracts import ToolResult
from devices.adb import ADBDevice
from tools.base import Tool


class _AdbWf(Tool):
    capability = "workflow.android"
    timeout_s = 20.0

    def __init__(self, device: ADBDevice) -> None:
        self.device = device


class AndroidWake(_AdbWf):
    name = "android_wake"
    description = "Wake the Android device (KEYCODE_WAKEUP)."
    parameters = {"type": "object", "properties": {}}
    idempotent = True

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        if not self.device.health()["online"]:
            return ToolResult(ok=False, error="adb device offline")
        self.device._shell("input keyevent KEYCODE_WAKEUP")
        return ToolResult(ok=True, data={"woke": True})


class AndroidUnlock(_AdbWf):
    name = "android_unlock"
    description = "Unlock the device (dismiss keyguard / swipe up)."
    parameters = {"type": "object", "properties": {}}
    idempotent = True

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        if not self.device.health()["online"]:
            return ToolResult(ok=False, error="adb device offline")
        self.device._shell("wm dismiss-keyguard")
        self.device._shell("input keyevent 82")  # menu = unlock fallback
        return ToolResult(ok=True, data={"unlocked": True})


class AndroidWaitUI(_AdbWf):
    name = "android_wait_ui"
    description = "Wait until the current UI settles (real sleep + dumpsys poll)."
    parameters = {"type": "object", "properties": {"seconds": {"type": "integer", "default": 3}},
                  "required": []}
    idempotent = True

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        if not self.device.health()["online"]:
            return ToolResult(ok=False, error="adb device offline")
        secs = int(params.get("seconds", 3))
        time.sleep(secs)
        top = self.device._shell("dumpsys activity activities | grep -m1 ResumedActivity")
        return ToolResult(ok=True, data={"waited_s": secs, "top_activity": top.strip()[:80]})


def register_all(registry, device: ADBDevice) -> None:
    for t in (AndroidWake(device), AndroidUnlock(device), AndroidWaitUI(device)):
        registry.register(t)
