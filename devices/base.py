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
    """Registry of devices; command fan-out; online/offline tracking."""

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

    async def execute(self, device_name: str, command: str,
                      params: dict[str, Any]) -> ToolResult:
        dev = self._devices.get(device_name)
        if dev is None:
            return ToolResult(ok=False, error=f"unknown device: {device_name}")
        if not dev.health().get("online", False):
            return ToolResult(ok=False, error=f"device offline: {device_name}", data={"blocked": True})
        return await dev.execute(command, params)
