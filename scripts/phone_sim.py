#!/usr/bin/env python3
"""AgentCore — scripts/phone_sim.py
Phone companion SIMULATOR. Speaks the same wire protocol as the Kotlin app
(devices/companion_app/) so the laptop↔phone transport can be tested without
a physical Android device.

Usage:
  python scripts/phone_sim.py --pair <CODE>            # pair with a code from /api/devices/pair
  python scripts/phone_sim.py --token <TOKEN>          # reconnect with an issued token
  python scripts/phone_sim.py --host localhost --port 9000

The simulator connects, completes pairing, then answers every command with a
plausible fake result (open_app → ok; screenshot → fake path; etc.).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import sys
import time

DEFAULT = "ws://localhost:9000/ws/android"


def sign(env: dict, token: str) -> dict:
    msg = f"{env['id']}|{env['type']}|{env['cmd']}|{env['ts']}".encode()
    env = dict(env)
    env["auth"] = {"token": hmac.new(token.encode(), msg, hashlib.sha256).hexdigest()}
    return env


# fake executors — mirror what the Kotlin app will do
def execute(cmd: str, params: dict) -> dict:
    if cmd == "device.android.open_app":
        return {"ok": True, "data": {"opened": params.get("app"),
                                     "package": f"com.example.{params.get('app','app')}"}}
    if cmd == "device.android.open_url":
        return {"ok": True, "data": {"url": params.get("url")}}
    if cmd == "device.android.open_youtube":
        return {"ok": True, "data": {"query": params.get("query"),
                                     "opened_in": "youtube-app"}}
    if cmd == "device.android.open_whatsapp":
        return {"ok": True, "data": {"number": params.get("number", "none")}}
    if cmd == "device.android.open_settings":
        return {"ok": True, "data": {"panel": params.get("panel")}}
    if cmd == "device.android.read_notifications":
        return {"ok": True, "data": {"notifications": [
            {"app": "WhatsApp", "title": "Family group", "text": "See you at 6",
             "time": time.time() - 120},
            {"app": "Gmail", "title": "DSA course", "text": "New lesson available",
             "time": time.time() - 900},
        ]}}
    if cmd == "device.android.screenshot":
        return {"ok": True, "data": {"file": "/storage/emulated/0/Pictures/agentcore/shot_1.png",
                                     "size": 812345, "mime": "image/png"}}
    if cmd == "device.android.get_foreground_app":
        return {"ok": True, "data": {"app": "com.whatsapp"}}
    if cmd == "device.android.clipboard":
        if params.get("action") == "get":
            return {"ok": True, "data": {"clipboard": "hello from phone"}}
        return {"ok": True, "data": {"set": params.get("text")}}
    if cmd == "device.android.share_file":
        return {"ok": True, "data": {"shared": params.get("path")}}
    return {"ok": False, "error": f"unknown command {cmd}"}


async def main() -> None:
    ap = argparse.ArgumentParser(description="AgentCore phone simulator")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--pair", default="", help="6-digit pairing code")
    ap.add_argument("--token", default="", help="existing device token")
    ap.add_argument("--name", default="Pixel 7 (sim)")
    args = ap.parse_args()

    import websockets
    url = f"ws://{args.host}:{args.port}/ws/android"
    print(f"📱 phone simulator connecting to {url}")

    async with websockets.connect(url, ping_interval=None) as ws:
        # hello
        hello = {"v": 1, "id": "hello_1", "type": "hello", "device": args.name,
                 "code": args.pair, "ts": time.time()}
        if args.token:
            hello = sign({**hello, "code": ""}, args.token)
        await ws.send(json.dumps(hello))
        resp = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if resp["type"] == "pair_error":
            print(f"❌ pairing rejected: {resp.get('data', {}).get('error')}")
            sys.exit(1)
        token = resp["data"]["token"]
        print(f"✅ paired as '{resp['device']}' — token={token[:8]}…")
        print(f"   commands supported: {len(resp['data']['commands'])}")
        print("   📱 listening for commands… (Ctrl-C to stop)")

        heartbeat = 0
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), 15)
            except asyncio.TimeoutError:
                # periodic heartbeat (mirrors Kotlin ConnectionManager)
                hb = sign({"v": 1, "id": f"hb_{heartbeat}", "type": "heartbeat",
                           "cmd": "", "ts": time.time()}, token)
                await ws.send(json.dumps(hb))
                heartbeat += 1
                continue
            env = json.loads(raw)
            if env["type"] != "command":
                continue
            # ack first, then execute + result (mirrors Kotlin CommandExecutor)
            ack = sign({"v": 1, "id": env["id"], "type": "ack", "cmd": env["cmd"],
                        "ts": time.time()}, token)
            await ws.send(json.dumps(ack))
            print(f"   ▶ received command: {env['cmd']} {env.get('params', {})}")
            result = execute(env["cmd"], env.get("params", {}))
            res_env = sign({"v": 1, "id": env["id"], "type": "result",
                            "cmd": env["cmd"], "data": result, "ts": time.time()}, token)
            await ws.send(json.dumps(res_env))
            print(f"   ✓ replied: {result}")


if __name__ == "__main__":
    asyncio.run(main())
