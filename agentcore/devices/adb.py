"""AgentCore — devices/adb.py
REAL ADB transport for the Android vertical slice (no mocks).

Uses `adb-shell` — a pure-Python implementation of the REAL ADB wire protocol
(the same protocol the `adb` CLI speaks to a device/emulator). Every command
here is a genuine adb `shell`/`exec-out` call against a connected device
(TCP: host:5555 by default — emulator or `adb connect <ip>:5555`).

  ADBDevice implements the Device ABC, so it plugs into the DeviceManager
  exactly like WindowsDevice / AndroidDevice(WS). The Executor drives it via
  the android_* tools with device_id="adb" (or automatic fallback).

All commands: structured logging, timeouts, real result/error surfaces.
"""
from __future__ import annotations

import base64
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

import structlog

from core.contracts import ToolResult
from devices.base import Device

log = structlog.get_logger("agentcore.devices.adb")

# key files (like ~/.android/adbkey — generated once, reused across sessions)
_KEYS_DIR = Path(__file__).resolve().parent.parent / "data" / "adb"
_AUTH_PUB = _KEYS_DIR / "adbkey.pub"
_AUTH_PRIV = _KEYS_DIR / "adbkey"

_COMMON_PACKAGES = {
    "whatsapp": "com.whatsapp",
    "youtube": "com.google.android.youtube",
    "settings": "com.android.settings",
    "camera": "com.android.camera",
    "chrome": "com.android.chrome",
    "gmail": "com.google.android.gm",
    "maps": "com.google.android.apps.maps",
    "phone": "com.google.android.dialer",
    "playstore": "com.android.vending",
    "calculator": "com.google.android.calculator",
}

_CAPABILITIES = [
    "device.android.open_app", "device.android.open_url",
    "device.android.open_youtube", "device.android.open_whatsapp",
    "device.android.open_settings", "device.android.read_notifications",
    "device.android.screenshot", "device.android.get_foreground_app",
    "device.android.clipboard", "device.android.share_file",
    "device.android.ui_tap", "device.android.ui_swipe", "device.android.ui_text",
    "device.android.report_capabilities",
]


class ADBDevice(Device):
    """Real ADB device. `connect()` opens a TCP connection to adbd."""

    name = "adb"
    platform = "android"

    def __init__(self, host: str = "127.0.0.1", port: int = 5555,
                 serial: str = "", screenshots_dir: str | None = None,
                 connect_timeout: float = 6.0) -> None:
        self.host = host
        self.port = port
        self.serial = serial or f"{host}:{port}"
        self.connect_timeout = connect_timeout
        self.screens_dir = Path(screenshots_dir or (
            Path(__file__).resolve().parent.parent / "data" / "screenshots"))
        self.screens_dir.mkdir(parents=True, exist_ok=True)
        self._dev = None
        self._online = False
        self._ensure_keys()

    # ------------------------------------------------------------------ auth
    def _ensure_keys(self) -> None:
        """Generate an RSA keypair like `adb` does (real device auth)."""
        try:
            from adb_shell.auth.keygen import keygen
            if not _AUTH_PUB.exists():
                _KEYS_DIR.mkdir(parents=True, exist_ok=True)
                keygen(str(_AUTH_PRIV))
                log.info("generated adb auth key", path=str(_AUTH_PRIV))
        except Exception as e:  # noqa: BLE001
            log.warning("adb keygen failed", error=str(e))

    # ------------------------------------------------------------------ lifecycle
    def connect(self) -> bool:
        from adb_shell.adb_device import AdbDeviceTcp
        try:
            dev = AdbDeviceTcp(self.host, self.port, default_transport_timeout_s=9.0)
            dev.connect(rsa_keys=[str(_AUTH_PRIV)] if _AUTH_PRIV.exists() else [],
                        auth_timeout_s=10.0)
            # real ping: run a trivial shell command to confirm the channel
            dev.shell("echo ok", timeout_s=5.0)
            self._dev = dev
            self._online = True
            log.info("adb device connected", serial=self.serial)
            return True
        except Exception as e:  # noqa: BLE001
            self._dev = None
            self._online = False
            log.info("adb device offline", serial=self.serial, error=str(e)[:100])
            return False

    def health(self) -> dict[str, Any]:
        return {"online": self._online, "serial": self.serial,
                "host": self.host, "port": self.port,
                "transport": "adb"}

    def disconnect(self) -> None:
        try:
            if self._dev is not None:
                self._dev.close()
        except Exception:  # noqa: BLE001
            pass
        self._dev = None
        self._online = False

    # ------------------------------------------------------------------ primitives
    def _shell(self, cmd: str, timeout: float = 15.0) -> str:
        """Run a real shell command on the device; returns stdout."""
        if self._dev is None or not self._online:
            raise ConnectionError(f"adb device offline: {self.serial}")
        out = self._dev.shell(cmd, timeout_s=timeout)
        log.debug("adb shell", serial=self.serial, cmd=cmd[:120],
                  out_len=len(out or ""))
        return out or ""

    def _exec_out(self, cmd: str, timeout: float = 20.0) -> bytes:
        """exec-out (binary-safe, used for screencap)."""
        if self._dev is None or not self._online:
            raise ConnectionError(f"adb device offline: {self.serial}")
        data = self._dev.exec_out(cmd, timeout_s=timeout)
        log.debug("adb exec-out", serial=self.serial, cmd=cmd[:80],
                  bytes=len(data or b""))
        return data or b""

    def _input(self, *args: str) -> str:
        quoted = " ".join(_shell_quote(a) for a in args)
        return self._shell(f"input {quoted}")

    # ------------------------------------------------------------------ capabilities
    def capabilities(self) -> list[str]:
        return list(_CAPABILITIES)

    # ------------------------------------------------------------------ command map
    async def execute(self, command: str, params: dict[str, Any],
                      timeout: float = 30.0) -> ToolResult:
        if command not in _CAPABILITIES:
            return ToolResult(ok=False, error=f"adb cannot execute {command}")
        if not self._online:
            return ToolResult(ok=False, error=f"adb device offline: {self.serial}",
                              data={"blocked": True, "serial": self.serial})
        try:
            fn = getattr(self, "_cmd_" + command.split(".")[-1], None)
            if fn is None:
                return ToolResult(ok=False, error=f"no handler for {command}")
            data = await fn(params, timeout)
            return ToolResult(ok=True, data=data)
        except Exception as e:  # noqa: BLE001
            log.warning("adb command failed", cmd=command, error=str(e)[:160])
            return ToolResult(ok=False, error=f"{command}: {e}")

    # --- real command implementations --------------------------------------
    async def _cmd_open_app(self, p: dict, t: float) -> dict:
        app = (p.get("app") or "").lower()
        pkg = _COMMON_PACKAGES.get(app, app)
        # resolve the real launcher activity, then start it
        resolve = self._shell(f'cmd package resolve-activity --brief {pkg}', t)
        activity = (resolve.strip().splitlines()[-1:] or [""])[0].strip()
        if not activity or "Error" in activity or activity == pkg:
            # fallback: monkey launch
            self._shell(f'monkey -p {pkg} -c android.intent.category.LAUNCHER 1', t)
        else:
            self._shell(f'am start -n {activity}', t)
        return {"opened": app, "package": pkg, "activity": activity}

    async def _cmd_open_url(self, p: dict, t: float) -> dict:
        url = p.get("url", "")
        self._shell(f'am start -a android.intent.action.VIEW -d "{_shell_quote(url)}"', t)
        return {"url": url}

    async def _cmd_open_youtube(self, p: dict, t: float) -> dict:
        q = p.get("query", "")
        url = ("https://www.youtube.com/results?search_query="
               + urllib.parse.quote_plus(q)) if q else "https://www.youtube.com"
        self._shell(f'am start -a android.intent.action.VIEW -d "{_shell_quote(url)}"', t)
        return {"query": q, "url": url}

    async def _cmd_open_whatsapp(self, p: dict, t: float) -> dict:
        num = (p.get("number") or "").strip()
        url = "https://wa.me/" + num if num else "https://wa.me/"
        self._shell(f'am start -a android.intent.action.VIEW -d "{_shell_quote(url)}"', t)
        return {"number": num}

    async def _cmd_open_settings(self, p: dict, t: float) -> dict:
        panel = (p.get("panel") or "settings").lower()
        intents = {"wifi": "android.settings.WIFI_SETTINGS",
                   "bluetooth": "android.settings.BLUETOOTH_SETTINGS",
                   "battery": "android.settings.BATTERY_SAVER_SETTINGS",
                   "data": "android.settings.DATA_ROAMING_SETTINGS",
                   "settings": "android.settings.SETTINGS"}
        self._shell(f'am start -a {intents.get(panel, intents["settings"])}', t)
        return {"panel": panel}

    async def _cmd_screenshot(self, p: dict, t: float) -> dict:
        png = self._exec_out("screencap -p", t)
        if not png or len(png) < 1000:
            raise RuntimeError(f"screencap returned {len(png or b'')} bytes")
        fname = f"shot_{int(time.time()*1000)}.png"
        path = self.screens_dir / fname
        path.write_bytes(png)
        log.info("screenshot captured", path=str(path), size=len(png))
        return {"file": str(path), "size": len(png), "mime": "image/png",
                "serial": self.serial}

    async def _cmd_get_foreground_app(self, p: dict, t: float) -> dict:
        out = self._shell("dumpsys activity activities | grep -m1 ResumedActivity", t)
        m = re.search(r"ResumedActivity.*?([\w.]+/[\w.]+)", out)
        return {"app": m.group(1) if m else "unknown"}

    async def _cmd_clipboard(self, p: dict, t: float) -> dict:
        action = p.get("action", "get")
        if action == "get":
            txt = self._shell("cmd clipboard get-text", t).strip()
            return {"clipboard": txt}
        text = p.get("text", "")
        self._shell(f'cmd clipboard set-text "{_shell_quote(text)}"', t)
        return {"set": text}

    async def _cmd_read_notifications(self, p: dict, t: float) -> dict:
        out = self._shell("dumpsys notification --noredact", t)
        # best-effort real parse: group by package, collect titles
        notifs = []
        for m in re.finditer(r'pkg=([\w.]+).*?android\.title=(\S+)', out):
            notifs.append({"app": m.group(1), "title": m.group(2)[:120]})
            if len(notifs) >= 20:
                break
        return {"notifications": notifs}

    async def _cmd_ui_tap(self, p: dict, t: float) -> dict:
        self._input("tap", str(int(p.get("x", 0))), str(int(p.get("y", 0))))
        return {"tapped": [p.get("x"), p.get("y")]}

    async def _cmd_ui_swipe(self, p: dict, t: float) -> dict:
        self._input("swipe", str(int(p.get("x1", 0))), str(int(p.get("y1", 0))),
                    str(int(p.get("x2", 0))), str(int(p.get("y2", 0))))
        return {"swiped": [p.get("x1"), p.get("y1"), p.get("x2"), p.get("y2")]}

    async def _cmd_ui_text(self, p: dict, t: float) -> dict:
        text = p.get("text", "")
        # `input text` needs spaces escaped as %s
        escaped = text.replace(" ", "%s")
        self._input("text", escaped)
        return {"typed": text[:60]}

    async def _cmd_share_file(self, p: dict, t: float) -> dict:
        path = p.get("path", "")
        # real: push the file to the device, then `am start` a chooser is
        # device-dependent; minimal real behavior: verify + push
        local = Path(path)
        if not local.exists():
            raise FileNotFoundError(path)
        remote = f"/sdcard/Download/{local.name}"
        if self._dev is not None:
            self._dev.push(local, remote)
        return {"shared": path, "pushed_to": remote}

    async def _cmd_report_capabilities(self, p: dict, t: float) -> dict:
        devices = self._shell("getprop ro.product.model", t).strip()
        sdk = self._shell("getprop ro.build.version.sdk", t).strip()
        return {"device": devices, "sdk": sdk,
                "executors": _CAPABILITIES, "transport": "adb",
                "screenshot_capture": "screencap"}


def _shell_quote(s: str) -> str:
    """Escape a string for a shell command line (adb shell runs via sh)."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`") \
            .replace("$", "\\$").replace(";", "\\;").replace("|", "\\|")
