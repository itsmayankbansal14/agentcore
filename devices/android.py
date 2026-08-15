"""AgentCore — devices/android.py
AndroidDevice — REAL transport for the companion app (Phase 5).

Architecture:
  * The LAPTOP is the WebSocket server (/ws/android). The PHONE connects to it.
  * Pairing: laptop issues a 6-digit one-time code → phone sends {"hello",
    pair_code} → laptop validates, issues a persistent device_token → phone
    stores it (Keystore) and presents it on future connections.
  * Commands: agent tool call → execute() → signed Envelope over the WS →
    phone acks, then replies a result → matched by envelope id via
    asyncio.Future. Correlation, never fire-and-forget.
  * Heartbeats keep the link alive; timeouts mark the device offline.

The Kotlin app (devices/companion_app/) mirrors this protocol exactly; the
wire format is verified by scripts/phone_sim.py.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from core.contracts import ToolResult
from devices.base import Device

log = structlog.get_logger("agentcore.devices.android")

APP_CMD_CAPABILITIES = [
    "device.android.open_app",
    "device.android.open_url",
    "device.android.open_youtube",
    "device.android.open_whatsapp",
    "device.android.open_settings",
    "device.android.read_notifications",
    "device.android.screenshot",
    "device.android.get_foreground_app",
    "device.android.clipboard",
    "device.android.share_file",
    # Phase 6: accessibility UI control + capability reporting
    "device.android.ui_tap",
    "device.android.ui_swipe",
    "device.android.ui_text",
    "device.android.report_capabilities",
]

# non-command messages the phone can send
_TYPES = {"command", "ack", "result", "event", "heartbeat", "error",
          "hello", "paired", "pair_error"}

PAIR_CODE_TTL_S = 120          # pairing code valid for 2 minutes
COMMAND_TIMEOUT_S = 45
HEARTBEAT_TIMEOUT_S = 90


# ---------------------------------------------------------------------------
# Protocol envelope (mirrored in Kotlin: Protocol.kt)
# ---------------------------------------------------------------------------
@dataclass
class Envelope:
    v: int = 1
    id: str = ""
    type: str = "command"
    device: str = ""
    cmd: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    data: Any = None
    ts: float = field(default_factory=time.time)
    token: str = ""
    code: str = ""            # pairing code (hello only)

    def to_json(self) -> str:
        return json.dumps({
            "v": self.v, "id": self.id, "type": self.type, "device": self.device,
            "cmd": self.cmd, "params": self.params, "data": self.data,
            "ts": self.ts, "auth": {"token": self.token}, "code": self.code,
        })

    @classmethod
    def from_json(cls, raw: str | dict) -> "Envelope":
        d = json.loads(raw) if isinstance(raw, str) else raw
        auth = d.pop("auth", {}) or {}
        return cls(**{**d, "token": auth.get("token", ""), "code": d.get("code", "")})


def sign_envelope(env: Envelope, token: str) -> Envelope:
    msg = f"{env.id}|{env.type}|{env.cmd}|{env.ts}".encode()
    env.token = hmac.new(token.encode(), msg, hashlib.sha256).hexdigest()
    return env


def verify_envelope(env: Envelope, token: str, max_age_s: float = 60.0) -> bool:
    if abs(time.time() - env.ts) > max_age_s:
        return False
    msg = f"{env.id}|{env.type}|{env.cmd}|{env.ts}".encode()
    expected = hmac.new(token.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, env.token)


# ---------------------------------------------------------------------------
class AndroidDevice(Device):
    name = "android"
    platform = "android"

    def __init__(self, fingerprint: str = "", db=None) -> None:
        self.fingerprint = fingerprint or "unpaired"
        self.db = db                       # optional Database for device persistence
        self._ws: Any = None               # current websocket (starlette)
        self._token: str = ""              # current session device token
        self._pair_code: str | None = None
        self._pair_code_expires: float = 0.0
        self._pending: dict[str, asyncio.Future] = {}
        self._online = False
        self._last_seen: float | None = None
        self._capabilities_reported: list[str] = []

    # ------------------------------------------------------------------ identity
    @property
    def token(self) -> str:
        return self._token

    # ------------------------------------------------------------------ pairing
    def start_pairing(self) -> dict:
        """Generate a one-time 6-digit code. Returns code + expiry."""
        self._pair_code = f"{secrets.randbelow(10**6):06d}"
        self._pair_code_expires = time.time() + PAIR_CODE_TTL_S
        log.info("pairing started", device=self.name)
        return {"pair_code": self._pair_code,
                "expires_at": self._pair_code_expires,
                "expires_in_s": PAIR_CODE_TTL_S}

    def _pair_code_valid(self, code: str) -> bool:
        return (self._pair_code is not None
                and secrets.compare_digest(self._pair_code, code)
                and time.time() < self._pair_code_expires)

    def _issue_token(self) -> str:
        self._token = secrets.token_hex(32)
        self._persist()
        return self._token

    def _persist(self) -> None:
        if self.db is None:
            return
        try:
            from database.models import Device as DeviceRow
            with self.db.session() as s:
                row = s.query(DeviceRow).filter_by(fingerprint=self.fingerprint).first()
                if row is None:
                    row = DeviceRow(name=self.fingerprint, fingerprint=self.fingerprint)
                    s.add(row)
                import hashlib as _h
                row.device_token_hash = _h.sha256(self._token.encode()).hexdigest()
                row.connection_state = "online" if self._online else "offline"
                from datetime import datetime, timezone
                row.last_seen = datetime.now(timezone.utc).isoformat()
                s.commit()
        except Exception:  # noqa: BLE001
            log.warning("device persist failed")

    def _load_token_for(self, fingerprint: str) -> str | None:
        if self.db is None:
            return None
        try:
            import hashlib as _h
            from database.models import Device as DeviceRow
            with self.db.session() as s:
                row = s.query(DeviceRow).filter_by(fingerprint=fingerprint).first()
                if row and row.device_token_hash:
                    return row.device_token_hash  # we store the hash; see note below
        except Exception:  # noqa: BLE001
            pass
        return None

    # ------------------------------------------------------------------ transport
    async def attach(self, ws) -> bool:
        """Server endpoint hands us a new inbound connection.
        Single-device MVP: reject a second live connection so an old socket
        never clobbers the active one."""
        if self._online and self._ws is not None:
            log.warning("android already connected — rejecting new connection")
            try:
                await ws.close(code=4001, reason="device already connected")
            except Exception:  # noqa: BLE001
                pass
            return False
        self._ws = ws
        self._online = True
        self._last_seen = time.time()
        self._pending.clear()
        # spawn receive loop
        asyncio.create_task(self._receive_loop())
        return True

    async def _receive_loop(self) -> None:
        try:
            while True:
                raw = await self._ws.receive_text()
                env = Envelope.from_json(raw)
                self._last_seen = time.time()
                await self._handle(env)
        except Exception as e:  # noqa: BLE001 — connection dropped
            log.info("android connection closed", error=str(e)[:80])
        finally:
            self._online = False
            self._ws = None
            # fail all pending commands so the agent doesn't hang
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_result(ToolResult(ok=False, error="android disconnected"))
            self._pending.clear()
            self._persist()

    async def _handle(self, env: Envelope) -> None:
        if env.type == "hello":
            await self._handle_hello(env)
            return
        # ack/result/event must be authenticated
        if env.type in ("ack", "result", "event", "heartbeat", "error"):
            if not verify_envelope(env, self._token):
                log.warning("rejected unauthenticated message", type=env.type)
                return
            if env.type == "heartbeat":
                return
            if env.type == "ack":
                # acknowledgment only — NEVER resolves the command future;
                # the terminal outcome arrives as a separate `result` envelope.
                return
            if env.type in ("result", "error"):
                fut = self._pending.pop(env.id, None)
                if fut is not None and not fut.done():
                    if env.type == "result":
                        fut.set_result(ToolResult(
                            ok=bool(env.data.get("ok", True)) if isinstance(env.data, dict) else True,
                            data=env.data, error=env.data.get("error") if isinstance(env.data, dict) else None))
                    else:  # error envelope
                        fut.set_result(ToolResult(ok=False,
                                                  error=(env.data or {}).get("error", "android error")
                                                  if isinstance(env.data, dict) else str(env.data)))
            return
        log.warning("unexpected message type", type=env.type)

    async def _handle_hello(self, env: Envelope) -> None:
        """Pairing handshake. Two paths:
          1) pair_code present → validate, issue token, reply paired
          2) token present → verify against stored token, reply paired
        """
        try:
            if env.code:
                if not self._pair_code_valid(env.code):
                    await self._ws.send_text(json.dumps(
                        {"v": 1, "type": "pair_error", "id": env.id or "pair",
                         "data": {"error": "invalid or expired pair code"}, "ts": time.time()}))
                    log.warning("bad pair code attempt")
                    return
                self.fingerprint = env.device or f"android-{env.id[:6]}"
                token = self._issue_token()
                log.info("phone paired", device=self.fingerprint)
            elif env.token:
                # compare with current session token (kept in memory for MVP; DB hash for restart)
                if not self._token or not hmac.compare_digest(self._token, env.token):
                    log.warning("rejected hello: bad token")
                    await self._ws.send_text(json.dumps(
                        {"v": 1, "type": "pair_error", "id": env.id or "pair",
                         "data": {"error": "invalid token"}, "ts": time.time()}))
                    return
                token = self._token
            else:
                await self._ws.send_text(json.dumps(
                    {"v": 1, "type": "pair_error", "id": env.id or "pair",
                     "data": {"error": "missing pair_code or token"}, "ts": time.time()}))
                return

            await self._ws.send_text(json.dumps({
                "v": 1, "type": "paired", "id": env.id or "pair", "device": self.fingerprint,
                "data": {"token": token, "device_id": self.fingerprint,
                         "commands": APP_CMD_CAPABILITIES},
                "ts": time.time(),
            }))
            self._persist()
        except Exception as e:  # noqa: BLE001
            log.warning("hello handling failed", error=str(e))

    # ------------------------------------------------------------------ Device API
    def capabilities(self) -> list[str]:
        return list(APP_CMD_CAPABILITIES)

    def health(self) -> dict[str, Any]:
        return {"online": self._online, "last_seen": self._last_seen,
                "device": self.fingerprint, "paired": bool(self._token),
                "pending_commands": len(self._pending)}

    def connect(self) -> bool:
        # inbound: connection arrives via attach(); nothing to initiate
        return self._online

    async def execute(self, command: str, params: dict[str, Any],
                      timeout: float = COMMAND_TIMEOUT_S) -> ToolResult:
        """Send a command and await the phone's result (id-correlated)."""
        if command not in APP_CMD_CAPABILITIES:
            return ToolResult(ok=False, error=f"android cannot execute {command}")
        if not self._online or self._ws is None:
            return ToolResult(ok=False, error="android device offline",
                              data={"blocked": True})
        if not self._token:
            return ToolResult(ok=False, error="android device not paired",
                              data={"blocked": True})

        env = Envelope(id=f"cmd_{secrets.token_hex(4)}", type="command",
                       device=self.fingerprint, cmd=command, params=params)
        sign_envelope(env, self._token)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[env.id] = fut
        try:
            await self._ws.send_text(env.to_json())
            result = await asyncio.wait_for(fut, timeout)
            result.tool = command
            return result
        except asyncio.TimeoutError:
            self._pending.pop(env.id, None)
            return ToolResult(ok=False, error=f"command timed out ({command})",
                              data={"blocked": True, "command": command})
        except Exception as e:  # noqa: BLE001
            self._pending.pop(env.id, None)
            return ToolResult(ok=False, error=f"send failed: {e}")

    def disconnect(self) -> None:
        self._online = False
        self._ws = None
        self._persist()
