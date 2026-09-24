"""AgentCore — devices/adb.py
REAL ADB transport for the Android vertical slice (no mocks).

Uses `adb` CLI (subprocess-based) instead of adb-shell library.
Every command is a genuine adb `shell`/`exec-out` call against a connected
USB or TCP device (via `adb devices -l` discovery). The executor drives it via
android_* tools with device_id="adb" (or automatic fallback).

All commands: structured logging, timeouts, real result/error surfaces.

MIT License (adapted from JARVIS-v6 by Koay-YH-0102)

Copyright (c) 2026 Koay-YH-0102

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
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

def _shell_quote(s: str) -> str:
    """Escape a string for a shell command line (adb shell runs via sh)."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`") \
            .replace("$", "\\$").replace(";", "\\;").replace("|", "\\|")


class ADBDevice(Device):
    """Real ADB device. `connect()` discovers device via `adb devices -l`."""

    name = "adb"
    platform = "android"

    def __init__(self, host: str = "127.0.0.1", port: int = 5555,
                 serial: str = "", screenshots_dir: str | None = None,
                 connect_timeout: float = 6.0) -> None:
        # Keep host/port for backward compatibility but discovery uses `adb devices -l`
        self.host = host
        self.port = port
        self.serial = serial if serial else ""
        self.connect_timeout = connect_timeout
        self.screens_dir = Path(screenshots_dir or (
            Path(__file__).resolve().parent.parent / "data" / "screenshots"))
        self.screens_dir.mkdir(parents=True, exist_ok=True)
        self._online = False
        self._dev_serial = ""  # Real ADB serial discovered from `adb devices -l`
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
        """Discover and connect to a real ADB device via adb devices -l."""
        try:
            # Run adb devices -l to discover real devices (no serial needed for discovery)
            cmd = ["adb", "devices", "-l"]
            import subprocess
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            ok = result.returncode == 0
            output = result.stdout + result.stderr
            if not ok:
                log.info("adb discovery failed - adb not available")
                self._online = False
                return False

            # Parse adb devices -l output
            # Format: <serial>\t<state> product:<...>\ndevice <serial> product:<...>...
            lines = output.strip().split("\n")
            for line in lines[1:]:  # Skip header line
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                serial = parts[0]
                state = parts[1]
                
                # Only accept 'device' state (connected and authorized)
                if state == "device":
                    # Prefer the first online device
                    self._dev_serial = serial
                    self.serial = serial
                    break
                elif state in ("unauthorized", "offline", "unauth"):
                    log.info("adb device found but not ready", serial=serial, state=state)
                    self._dev_serial = ""
                    self.serial = ""
                    self._online = False
                    return False

            if not self._dev_serial:
                log.info("no adb device found", output=output[:200])
                self._online = False
                return False

            # Verify device is responsive with a simple ping
            ok, ping_output = self._run_adb_shell("echo ok", timeout=10)
            if not ok or "ok" not in ping_output:
                log.warning("adb device not responsive", serial=self._dev_serial)
                self._online = False
                return False

            self._online = True
            log.info("adb device connected", serial=self._dev_serial, state="device")
            return True

        except Exception as e:  # noqa: BLE001
            log.info("adb device offline", serial=self.serial if self.serial else "unknown", error=str(e)[:100])
            self._online = False
            return False

    def health(self) -> dict[str, Any]:
        return {"online": self._online, "serial": self._dev_serial or self.serial,
                "host": self.host, "port": self.port,
                "transport": "adb"}

    def disconnect(self) -> None:
        self._online = False
        self._dev_serial = ""

    # ------------------------------------------------------------------ ADB helpers (JARVIS-v6 pattern)
    def _run_adb(self, args: list[str], timeout: float = 10.0) -> tuple[bool, str]:
        """Run an adb command via subprocess, returns (ok, output).
        
        Note: For commands with shell pipes/redirections, args should be 
        passed as a single string to adb shell (e.g., ['shell', 'cmd | grep']).
        This method uses shell=True for proper handling of shell commands.
        """
        if not self._dev_serial and not self.serial:
            return False, "No device serial"
        
        # Build command string for shell=True
        cmd_parts = ["adb"]
        if self._dev_serial:
            cmd_parts.extend(["-s", self._dev_serial])
        cmd_parts.extend(args)
        
        # Join with proper quoting for Windows shell
        cmd_str = " ".join(f'"{arg}"' if " " in arg else arg for arg in cmd_parts)
        
        try:
            result = subprocess.run(cmd_str, capture_output=True, text=True, 
                                  timeout=timeout, shell=True)
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            log.warning("adb command timeout", cmd=cmd_str)
            return False, f"Timeout after {timeout}s"
        except Exception as e:
            log.warning("adb command failed", cmd=cmd_str, error=str(e))
            return False, str(e)

    def _run_adb_shell(self, cmd: str, timeout: float = 10.0) -> tuple[bool, str]:
        """Run adb shell command, returns (ok, output)."""
        # Don't check _online here - caller should handle that
        # For shell commands, pass the entire command as a string
        # adb shell will interpret it properly
        cmd_parts = ["shell", cmd]
        return self._run_adb(cmd_parts, timeout=timeout)

    # ------------------------------------------------------------------ primitives
    def _shell(self, cmd: str, timeout: float = 15.0) -> str:
        """Run a real shell command on the device; returns stdout."""
        if not self._online:
            raise ConnectionError(f"adb device offline: {self._dev_serial or self.serial}")
        
        ok, output = self._run_adb_shell(cmd, timeout=timeout)
        if not ok:
            raise ConnectionError(f"adb shell failed: {output}")
        
        log.debug("adb shell", serial=self._dev_serial or self.serial, cmd=cmd[:120],
                  out_len=len(output or ""))
        return output or ""

    def _exec_out(self, cmd: str, timeout: float = 20.0) -> bytes:
        """exec-out (binary-safe, used for screencap)."""
        if not self._online:
            raise ConnectionError(f"adb device offline: {self._dev_serial or self.serial}")
        
        # For exec-out, we need binary output
        if not self._dev_serial:
            raise ConnectionError(f"adb device offline: {self._dev_serial or self.serial}")
        
        cmd_parts = ["-s", self._dev_serial, "exec-out", cmd]
        try:
            result = subprocess.run(["adb"] + cmd_parts, capture_output=True, timeout=timeout)
            if result.returncode != 0:
                error_msg = result.stderr.decode("utf-8", errors="ignore")
                raise ConnectionError(f"adb exec-out failed: {error_msg}")
            log.debug("adb exec-out", serial=self._dev_serial, cmd=cmd[:80],
                      bytes=len(result.stdout or b""))
            return result.stdout or b""
        except subprocess.TimeoutExpired:
            log.warning("adb exec-out timeout", cmd=cmd)
            raise ConnectionError(f"adb exec-out timeout: {cmd}")
        except Exception as e:
            log.warning("adb exec-out failed", cmd=cmd, error=str(e))
            raise ConnectionError(f"adb exec-out failed: {e}")

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
            serial = self._dev_serial or self.serial
            return ToolResult(ok=False, error=f"adb device offline: {serial}",
                              data={"blocked": True, "serial": serial})
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
                "serial": self._dev_serial or self.serial}

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
        
        # Use adb push via subprocess
        if self._dev_serial:
            ok, output = self._run_adb(["push", str(local), remote], timeout=30)
            if not ok:
                raise RuntimeError(f"adb push failed: {output}")
        
        return {"shared": path, "pushed_to": remote}

    async def _cmd_report_capabilities(self, p: dict, t: float) -> dict:
        devices = self._shell("getprop ro.product.model", t).strip()
        sdk = self._shell("getprop ro.build.version.sdk", t).strip()
        return {"device": devices, "sdk": sdk,
                "executors": _CAPABILITIES, "transport": "adb",
                "screenshot_capture": "screencap"}
