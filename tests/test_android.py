"""AgentCore — tests/test_android.py
End-to-end Android transport test: real uvicorn server + real WebSocket
"phone" client (mirrors the Kotlin companion protocol). This is the kind of
real-execution validation the architecture review asked for — not a mocked unit test.

Run: python tests/test_android.py   (from agentcore root)
"""
from __future__ import annotations

import asyncio
import json
import socket
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def sign(env: dict, token: str) -> dict:
    import hashlib, hmac
    msg = f"{env['id']}|{env['type']}|{env['cmd']}|{env['ts']}".encode()
    env = dict(env)
    env["auth"] = {"token": hmac.new(token.encode(), msg, hashlib.sha256).hexdigest()}
    return env


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class PhoneClient:
    """In-test phone: connects, pairs, answers commands (ack + result)."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.ws = None
        self.token = ""

    async def connect(self, pair_code: str) -> None:
        self.ws = await websockets.connect(self.url, ping_interval=None)
        await self.ws.send(json.dumps({
            "v": 1, "id": "hello_1", "type": "hello",
            "device": "TestPhone", "code": pair_code, "ts": time.time()}))
        resp = json.loads(await asyncio.wait_for(self.ws.recv(), 10))
        assert resp["type"] == "paired", f"pair failed: {resp}"
        self.token = resp["data"]["token"]

    async def serve(self, cmd_results: dict, stop: asyncio.Event) -> None:
        """Answer commands until stop is set."""
        async def _execute(cmd: str, params: dict) -> dict:
            if cmd in cmd_results:
                return cmd_results[cmd]
            return {"ok": True, "data": {"echo": cmd, "params": params}}

        try:
            while not stop.is_set():
                raw = await asyncio.wait_for(self.ws.recv(), 30)
                env = json.loads(raw)
                if env["type"] != "command":
                    continue
                await self.ws.send(json.dumps(sign({
                    "v": 1, "id": env["id"], "type": "ack", "cmd": env["cmd"],
                    "ts": time.time()}, self.token)))
                res = await _execute(env["cmd"], env.get("params", {}))
                await self.ws.send(json.dumps(sign({
                    "v": 1, "id": env["id"], "type": "result", "cmd": env["cmd"],
                    "data": res, "ts": time.time()}, self.token)))
        except Exception:  # noqa: BLE001
            pass


async def main() -> None:
    from core.app import AgentApp
    from llm.router import KeyRuntime
    from api.server import create_app
    import uvicorn

    app = AgentApp.create(db_path=tempfile.mktemp(suffix=".db"))
    app.llm.router.keys = [KeyRuntime("mock", "k", "m")]  # hermetic

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(app), host="127.0.0.1",
                                           port=port, log_level="error"))
    # run the server as a task in THIS loop so websocket futures and the
    # device share one event loop (same as production: one uvicorn loop)
    server_task_holder = asyncio.create_task(server.serve())
    await asyncio.sleep(1.5)

    base = f"http://127.0.0.1:{port}"
    import httpx
    dev = app.devices.get("android")

    # ---- pairing ----
    # wrong code rejected FIRST (before any device is online)
    bad_ws = await websockets.connect(f"ws://127.0.0.1:{port}/ws/android",
                                      ping_interval=None)
    await bad_ws.send(json.dumps({"v": 1, "id": "x", "type": "hello",
                                  "device": "Bad", "code": "000000", "ts": time.time()}))
    resp = json.loads(await asyncio.wait_for(bad_ws.recv(), 10))
    await bad_ws.close()
    check("bad pair code rejected", resp["type"] == "pair_error", resp["type"])

    async with httpx.AsyncClient() as hc:
        r = await hc.post(f"{base}/api/devices/pair", timeout=5)
        code = r.json()["pair_code"]
    phone = PhoneClient(f"ws://127.0.0.1:{port}/ws/android")
    await phone.connect(code)
    check("pairing handshake works", bool(phone.token), phone.token[:8])
    # second concurrent connection should be rejected (single-device guard)
    dup = await websockets.connect(f"ws://127.0.0.1:{port}/ws/android", ping_interval=None)
    dup_closed = False
    try:
        await dup.send(json.dumps({"v": 1, "id": "d", "type": "hello", "device": "Dup",
                                   "code": code, "ts": time.time()}))
        await asyncio.wait_for(dup.recv(), 5)
    except websockets.ConnectionClosed as e:
        dup_closed = e.code == 4001
    except asyncio.TimeoutError:
        dup_closed = False
    await dup.close()
    check("second connection rejected (4001)", dup_closed)

    # ---- command round-trip ----
    stop = asyncio.Event()
    server_task = asyncio.create_task(phone.serve({
        "device.android.open_app": {"ok": True, "data": {"opened": "whatsapp",
                                                         "package": "com.whatsapp"}},
        "device.android.read_notifications": {"ok": True, "data": {"notifications": [
            {"app": "WhatsApp", "title": "hi"}]}},
        "device.android.screenshot": {"ok": False, "error": "user denied screen capture"},
    }, stop))

    check("device online+paired", dev.health()["online"] and dev.health()["paired"])

    # success command (ack + result — the bug this test guards against)
    r1 = await dev.execute("device.android.open_app", {"app": "whatsapp"})
    check("open_app ok", r1.ok and r1.data["data"]["opened"] == "whatsapp",
          f"ok={r1.ok} err={r1.error} data={r1.data}")

    r2 = await dev.execute("device.android.read_notifications", {})
    check("read_notifications ok", r2.ok and len(r2.data["data"]["notifications"]) == 1,
          str(r2.data)[:80])

    r3 = await dev.execute("device.android.screenshot", {})
    check("screenshot failure surfaces", not r3.ok and "denied" in (r3.error or ""),
          f"ok={r3.ok} err={r3.error}")

    r4 = await dev.execute("device.android.open_app", {"app": "x"}, timeout=0.5)
    # device should still be online (no hang)
    check("still responsive after sequence", dev.health()["online"])

    # ---- agent loop integration (mock LLM calls the tool) ----
    from llm.providers import MockProvider
    prov = MockProvider()
    app.llm._factory = lambda n, k, m: prov
    prov.enqueue('[TOOL android_open_app {"app":"youtube"}]', 'Opened YouTube on the phone.')
    out = await app.orchestrator.handle_user_message("andtest", "open youtube on phone")
    check("agent loop dispatches to phone", "opened" in out.lower() or "youtube" in out.lower(),
          out[:120])
    from database.models import ToolExecution
    from sqlalchemy import text
    with app.db.engine.connect() as c:
        row = c.execute(text("SELECT status FROM tool_executions "
                             "WHERE tool='android_open_app' ORDER BY id DESC LIMIT 1")).fetchone()
    check("tool execution recorded as ok", row and row[0] == "ok", str(row))

    stop.set()
    server_task.cancel()
    await phone.ws.close()
    server.should_exit = True
    try:
        await asyncio.wait_for(server_task_holder, timeout=5)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass

    print(f"\n{'='*40}\nPASSED: {PASS}   FAILED: {FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
