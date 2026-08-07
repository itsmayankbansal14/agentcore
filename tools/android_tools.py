"""AgentCore — tools/android_tools.py
android.* tool family. Each tool is a thin wrapper that routes through the
DeviceManager → AndroidDevice.execute(capability, params). The LLM proposes
the command; the transport + phone execute it; the result comes back
id-correlated. Permission-gated like every other tool.
"""
from __future__ import annotations

from typing import Any

from core.contracts import ToolResult
from devices.base import DeviceManager
from tools.base import Tool


class _AndroidTool(Tool):
    capability = "device.android"

    def __init__(self, devices: DeviceManager) -> None:
        self.devices = devices

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        dev = self.devices.get("android")
        if dev is None:
            return ToolResult(ok=False, error="android device not registered")
        if not dev.health().get("online"):
            return ToolResult(ok=False, error="android device offline",
                              data={"blocked": True})
        return await dev.execute(self.cmd_name, params)


# -- concrete tools (each maps a capability) --------------------------------
class OpenAppTool(_AndroidTool):
    name = "android_open_app"
    description = "Open an app on the Android phone by package name or common name (whatsapp, youtube, settings, camera…)."
    parameters = {"type": "object", "properties": {"app": {"type": "string"}},
                  "required": ["app"]}
    cmd_name = "device.android.open_app"


class OpenUrlTool(_AndroidTool):
    name = "android_open_url"
    description = "Open a URL / deep link on the Android phone (ACTION_VIEW)."
    parameters = {"type": "object", "properties": {"url": {"type": "string"}},
                  "required": ["url"]}
    cmd_name = "device.android.open_url"


class OpenYoutubeTool(_AndroidTool):
    name = "android_open_youtube"
    description = "Search YouTube on the phone (youtube:// intent)."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}},
                  "required": ["query"]}
    cmd_name = "device.android.open_youtube"


class OpenWhatsappTool(_AndroidTool):
    name = "android_open_whatsapp"
    description = "Open WhatsApp, optionally to a phone number (wa.me)."
    parameters = {"type": "object",
                  "properties": {"number": {"type": "string"}}, "required": []}
    cmd_name = "device.android.open_whatsapp"


class OpenSettingsTool(_AndroidTool):
    name = "android_open_settings"
    description = "Open a system settings panel on the phone (wifi, bluetooth, battery…)."
    parameters = {"type": "object", "properties": {"panel": {"type": "string"}},
                  "required": ["panel"]}
    cmd_name = "device.android.open_settings"


class ReadNotificationsTool(_AndroidTool):
    name = "android_read_notifications"
    description = "Read recent notifications from the phone (requires Notification Access)."
    parameters = {"type": "object", "properties": {"since": {"type": "string"}},
                  "required": []}
    cmd_name = "device.android.read_notifications"


class ScreenshotTool(_AndroidTool):
    name = "android_screenshot"
    description = "Take a screenshot on the phone and return it (requires screen-capture permission)."
    parameters = {"type": "object", "properties": {}}
    cmd_name = "device.android.screenshot"


class ForegroundAppTool(_AndroidTool):
    name = "android_get_foreground_app"
    description = "Get the app currently in the foreground on the phone."
    parameters = {"type": "object", "properties": {}}
    cmd_name = "device.android.get_foreground_app"


class ClipboardTool(_AndroidTool):
    name = "android_clipboard"
    description = "Get or set the phone clipboard. action: get | set."
    parameters = {"type": "object",
                  "properties": {"action": {"type": "string", "enum": ["get", "set"]},
                                 "text": {"type": "string"}},
                  "required": ["action"]}
    cmd_name = "device.android.clipboard"


class ShareFileTool(_AndroidTool):
    name = "android_share_file"
    description = "Share/open a file path on the phone via the system picker."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}},
                  "required": ["path"]}
    cmd_name = "device.android.share_file"


def register_all(registry, devices: DeviceManager) -> None:
    for tool in (OpenAppTool(devices), OpenUrlTool(devices), OpenYoutubeTool(devices),
                 OpenWhatsappTool(devices), OpenSettingsTool(devices),
                 ReadNotificationsTool(devices), ScreenshotTool(devices),
                 ForegroundAppTool(devices), ClipboardTool(devices),
                 ShareFileTool(devices)):
        registry.register(tool)
