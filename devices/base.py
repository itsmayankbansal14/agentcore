"""AgentCore — devices/base.py
Device ABC — the abstraction the reviewer asked for: tools target
capabilities, and `device.execute(...)` routes them. Windows, Android,
future platforms (Linux, cloud, smart-home) all implement this.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.contracts import ToolResult


class Device(ABC):
    name: str = "device"
    platform: str = "generic"

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    async def execute(self, command: str, params: dict[str, Any]) -> ToolResult: ...

    @abstractmethod
    def capabilities(self) -> list[str]: ...

    @abstractmethod
    def health(self) -> dict[str, Any]: ...

    def disconnect(self) -> None:  # optional
        pass


class DeviceManager:
    """Registry of devices; command fan-out; online/offline tracking.
    Responsible for DETECTING connected devices (windows host, adb, browser
    runtime) and REPORTING their health. The Planner never queries Android
    directly — it requests capabilities; the DeviceManager selects devices."""

    def __init__(self) -> None:
        self._devices: dict[str, Device] = {}

    def register(self, device: Device) -> None:
        self._devices[device.name] = device

    def get(self, name: str) -> Device | None:
        return self._devices.get(name)

    def all(self) -> list[Device]:
        return list(self._devices.values())

    def online(self) -> list[Device]:
        return [d for d in self._devices.values() if d.health().get("online", False)]

    # -- detection -----------------------------------------------------------
    def detect(self) -> dict[str, dict]:
        """Probe and report every device's health (windows host, adb, browser)."""
        report = {}
        for name in ("windows", "android", "adb", "browser"):
            dev = self._devices.get(name)
            if dev is None:
                report[name] = {"online": False, "reason": "not registered"}
                continue
            try:
                report[name] = dev.health()
            except Exception as e:  # noqa: BLE001
                report[name] = {"online": False, "reason": str(e)[:80]}
        # adb: re-probe the transport for real device detection
        adb = self._devices.get("adb")
        if adb is not None:
            adb.connect()   # real TCP probe — updates online honestly
            report["adb"] = adb.health()
        return report

    def device_health(self) -> dict[str, dict]:
        """Aggregated health for the dashboard (stable shape)."""
        base = self.detect()
        out = {}
        for name, h in base.items():
            out[name] = {"online": bool(h.get("online")), "health": h,
                         "capabilities": (self._devices[name].capabilities()
                                          if name in self._devices else [])}
        return out

    async def execute(self, device_name: str, command: str,
                      params: dict[str, Any]) -> ToolResult:
        dev = self._devices.get(device_name)
        if dev is None:
            return ToolResult(ok=False, error=f"unknown device: {device_name}")
        if not dev.health().get("online", False):
            return ToolResult(ok=False, error=f"device offline: {device_name}", data={"blocked": True})
        return await dev.execute(command, params)
