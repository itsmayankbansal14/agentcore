"""AgentCore — devices/android.py
AndroidDevice skeleton + companion protocol.

Status: DESIGN-READY, NOT WIRED (no phone in this environment). The protocol
envelope and pairing handshake are defined; the WebSocket transport and the
companion app land in Phase 5/6 of the roadmap.

Command family (capability "device.android"):
  open_app, open_url, open_youtube, open_whatsapp, open_settings,
  read_notifications, screenshot, get_foreground_app, clipboard, share_file
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from dataclasses import dataclass, field

from core.contracts import ToolResult
from devices.base import Device

APP_CMD_CAPABILITIES = [
    "device.android.open_app", "device.android.open_url", "device.android.open_youtube",
    "device.android.open_whatsapp", "device.android.open_settings",
    "device.android.read_notifications", "device.android.screenshot",
    "device.android.get_foreground_app", "device.android.clipboard",
    "device.android.share_file",
]


# ---------------------------------------------------------------------------
# Protocol (mirrors what the Kotlin app will implement)
# ---------------------------------------------------------------------------
@dataclass
class Envelope:
    """One message laptop↔phone. Versioned; HMAC-authenticated."""
    v: int = 1
    id: str = ""
    type: str = "command"          # command | ack | result | event | heartbeat | error
    device: str = ""
    cmd: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    data: Any = None
    ts: float = field(default_factory=time.time)
    token: str = ""

    def to_json(self) -> str:
        return json.dumps({"v": self.v, "id": self.id, "type": self.type,
                           "device": self.device, "cmd": self.cmd,
                           "params": self.params, "data": self.data, "ts": self.ts,
                           "auth": {"token": self.token}})

    @classmethod
    def from_json(cls, raw: str) -> "Envelope":
        d = json.loads(raw)
        auth = d.pop("auth", {})
        return cls(**d, token=auth.get("token", ""))


def sign_envelope(envelope: Envelope, device_token: str) -> Envelope:
    """HMAC-SHA256 over id|cmd|ts — replay-safe with the ts window checked by receiver."""
    msg = f"{envelope.id}|{envelope.cmd}|{envelope.ts}".encode()
    envelope.token = hmac.new(device_token.encode(), msg, hashlib.sha256).hexdigest()
    return envelope


def verify_envelope(envelope: Envelope, device_token: str, max_age_s: float = 30.0) -> bool:
    if time.time() - envelope.ts > max_age_s:
        return False
    expected = hmac.new(device_token.encode(),
                        f"{envelope.id}|{envelope.cmd}|{envelope.ts}".encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, envelope.token)


# ---------------------------------------------------------------------------
class AndroidDevice(Device):
    name = "android"
    platform = "android"

    def __init__(self, fingerprint: str = "", device_token: str = "") -> None:
        self.fingerprint = fingerprint or "pixel-default"
        self._device_token = device_token or "dev-token"
        self._online = False
        self._last_seen: float | None = None

    def connect(self) -> bool:
        # Phase 5: WebSocket handshake + pairing verification
        self._online = True
        self._last_seen = time.time()
        return True

    def capabilities(self) -> list[str]:
        return list(APP_CMD_CAPABILITIES)

    def health(self) -> dict[str, Any]:
        return {"online": self._online, "last_seen": self._last_seen}

    async def execute(self, command: str, params: dict[str, Any]) -> ToolResult:
        if command not in APP_CMD_CAPABILITIES:
            return ToolResult(ok=False, error=f"android cannot execute {command}")
        if not self._online:
            return ToolResult(ok=False, error="android device offline", data={"blocked": True})

        # Phase 5/6: build signed envelope → WS send → await ack+result.
        env = Envelope(id=f"cmd_{int(time.time()*1000)}", type="command",
                       device=self.fingerprint, cmd=command, params=params)
        sign_envelope(env, self._device_token)
        # NOTE: transport not implemented yet — returns a structured "pending"
        # result so the planner/agent treats it as WAITING_TOOL, not a crash.
        return ToolResult(ok=True, data={
            "queued": True, "envelope": env.to_json(),
            "note": "Android transport lands in Phase 5 (WebSocket + companion app).",
        })

    def receive_event(self, raw: str) -> Envelope | None:
        env = Envelope.from_json(raw)
        if verify_envelope(env, self._device_token):
            self._last_seen = time.time()
            return env
        return None
