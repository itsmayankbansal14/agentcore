"""AgentCore — observer/observers.py
Concrete observers: filesystem, time, network, clipboard, system, android.
Screen observer is a stub (MediaProjection comes with the Android companion).
"""
from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from observer.base import Observation, Observer


class FilesystemObserver(Observer):
    source = "filesystem"

    def __init__(self, sandbox_root: str | None = None) -> None:
        self.sandbox = Path(sandbox_root).resolve() if sandbox_root else None

    def verify(self, tool_name, args, result) -> list[Observation]:
        if tool_name in ("fs_write", "fs_read", "fs_list", "knowledge_add"):
            path = (args.get("path") or (result or {}).get("path") or "")
            if path:
                p = Path(path).expanduser()
                # resolve relative paths against the sandbox (tools write there)
                if not p.is_absolute() and self.sandbox is not None:
                    p = (self.sandbox / p).resolve()
                exists = p.exists()
                return [Observation(
                    source=self.source, ok=exists,
                    data={"path": str(p), "exists": exists,
                          "size": p.stat().st_size if exists else None},
                    message=f"file {'exists' if exists else 'missing'}: {p.name}")]
        return []

    def poll(self) -> list[Observation]:
        if self.sandbox and self.sandbox.is_dir():
            n = sum(1 for _ in self.sandbox.rglob("*") if _.is_file())
            return [Observation(source=self.source, ok=True,
                                data={"sandbox_files": n},
                                message=f"sandbox has {n} files")]
        return []


class TimeObserver(Observer):
    source = "time"

    def verify(self, tool_name, args, result) -> list[Observation]:
        if tool_name == "time_now":
            now = datetime.now().strftime("%A, %d %B %Y, %I:%M %p")
            return [Observation(source=self.source, ok=True,
                                data={"now": now}, message=f"now: {now}")]
        return []

    def poll(self) -> list[Observation]:
        return [Observation(source=self.source, ok=True,
                            data={"ts": time.time()},
                            message=datetime.now().isoformat(timespec="seconds"))]


class NetworkObserver(Observer):
    source = "network"

    def __init__(self, host: str = "1.1.1.1") -> None:
        self.host = host

    def verify(self, tool_name, args, result) -> list[Observation]:
        # tools like web.fetch / knowledge_add may imply connectivity
        if tool_name in ("web_fetch", "music_youtube", "music_spotify"):
            ok = self._reachable()
            return [Observation(source=self.source, ok=ok,
                                data={"host": self.host},
                                message="network reachable" if ok else "network unreachable")]
        return []

    def poll(self) -> list[Observation]:
        ok = self._reachable()
        return [Observation(source=self.source, ok=ok, data={"host": self.host},
                            message="network reachable" if ok else "network unreachable")]

    def _reachable(self) -> bool:
        try:
            r = subprocess.run(["ping", "-c", "1", "-W", "2", self.host],
                               capture_output=True, timeout=4)
            return r.returncode == 0
        except Exception:
            return False


class ClipboardObserver(Observer):
    source = "clipboard"

    def verify(self, tool_name, args, result) -> list[Observation]:
        if tool_name == "clipboard_set":
            try:
                import pyperclip
                got = pyperclip.paste()
                expected = args.get("text", "")
                ok = bool(got) and got == expected
                return [Observation(source=self.source, ok=ok,
                                    data={"matches": ok},
                                    message="clipboard matches" if ok else "clipboard mismatch")]
            except Exception as e:  # noqa: BLE001
                return [Observation(source=self.source, ok=False,
                                    data={"error": str(e)},
                                    message="clipboard observer unavailable")]
        return []


class SystemObserver(Observer):
    source = "system"

    def poll(self) -> list[Observation]:
        import platform
        try:
            import psutil
            mem = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=0.1)
            data = {"platform": platform.system(), "cpu%": round(cpu, 1),
                    "mem%": mem.percent}
        except Exception:
            data = {"platform": platform.system()}
        return [Observation(source=self.source, ok=True, data=data,
                            message="system snapshot")]


class AndroidObserver(Observer):
    """Phone-state verification via the AndroidDevice's live health
    (WS transport, not ADB — ADB is only an optional extra)."""
    source = "android"

    def __init__(self, device=None) -> None:
        self._device = device   # AndroidDevice (or None → unknown)

    def _state(self) -> dict:
        if self._device is None:
            return {"online": False, "paired": False}
        h = self._device.health()
        return {"online": bool(h.get("online")), "paired": bool(h.get("paired")),
                "device": h.get("device")}

    def verify(self, tool_name, args, result) -> list[Observation]:
        if tool_name.startswith("android_"):
            st = self._state()
            ok = st["online"] and st["paired"]
            return [Observation(source=self.source, ok=ok,
                                data=st,
                                message=("phone connected & paired"
                                         if ok else "phone offline or unpaired"))]
        return []

    def poll(self) -> list[Observation]:
        st = self._state()
        return [Observation(source=self.source, ok=st["online"] and st["paired"],
                            data=st,
                            message="android device connected" if st["online"] else "android offline")]


class ScreenObserver(Observer):
    """Screen capture verification — enabled with the Android companion (Phase 5)."""
    source = "screen"

    def verify(self, tool_name, args, result) -> list[Observation]:
        return []
