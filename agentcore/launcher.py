"""AgentCore — launcher.py
Desktop launcher (the thing `AgentCore.exe` runs). It is NOT the runtime.

Responsibilities:
  - start the runtime  (FastAPI + WebSocket + AgentApp, one shared instance)
  - monitor the runtime (health checks, readiness)
  - stop the runtime gracefully (uvicorn should_exit + join)
  - optionally open the dashboard in the default browser
  - system-tray integration when available (pystray); graceful fallback to console

It contains NO planner/executor/memory logic — it only starts and supervises
the exact same runtime every other interface uses (dashboard.app.create_app).
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser

DEFAULT_PORT = 8000
DEFAULT_HOST = "127.0.0.1"   # localhost-only for the desktop app (browser + tray)


class RuntimeServerThread(threading.Thread):
    """Runs the shared FastAPI runtime over the same AgentApp used by voice."""

    def __init__(
        self,
        app,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        log_level: str = "warning",
    ) -> None:
        super().__init__(daemon=True, name="agentcore-runtime")
        self.app_instance = app
        self.host = host
        self.port = port
        self.log_level = log_level
        self.server = None

    def run(self) -> None:
        import uvicorn
        from dashboard.app import create_app

        application = create_app(self.app_instance)

        self.server = uvicorn.Server(
            uvicorn.Config(
                application,
                host=self.host,
                port=self.port,
                log_level=self.log_level,
            )
        )

        self.server.run()

    # -- supervision ------------------------------------------------------
    def wait_until_ready(self, timeout: float = 20.0) -> bool:
        import urllib.request
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        f"http://{self.host}:{self.port}/api/health", timeout=2) as r:
                    if r.status == 200:
                        return True
            except Exception:  # noqa: BLE001
                time.sleep(0.3)
        return False

    def stop(self, timeout: float = 8.0) -> None:
        if self.server is not None:
            self.server.should_exit = True
        self.join(timeout=timeout)
        if self.is_alive():
            print("[launcher] runtime did not stop in time")


class VoiceRuntimeThread(threading.Thread):
    """Runs the persistent VoiceManager over the shared AgentApp."""

    def __init__(self, app) -> None:
        super().__init__(
            daemon=True,
            name="agentcore-voice",
        )
        self.app_instance = app
        self.voice = None
        self.error: Exception | None = None

    def run(self) -> None:
        import asyncio
        try:
            from voice.manager import build_voice

            self.voice = build_voice(self.app_instance)

            health = self.voice.health()

            print("\n[voice] health:")
            for component, state in health.items():
                print(
                    f"[voice] {component}: "
                    f"{state.get('state', 'UNKNOWN')} "
                    f"- {state.get('detail', '')}"
                )

            if health["stt"]["state"] != "READY":
                raise RuntimeError(
                    f"STT is not ready: "
                    f"{health['stt'].get('detail', 'unknown error')}"
                )

            if health["microphone"]["state"] != "READY":
                raise RuntimeError(
                    f"Microphone unavailable: "
                    f"{health['microphone'].get('detail', '')}"
                )

            print("[voice] persistent voice runtime started")
            print("[voice] speak naturally — AgentCore is listening")

            # Use dedicated event loop (no asyncio.run inside thread)
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.voice.run_loop_async())

        except Exception as exc:
            self.error = exc
            print(f"[voice] FATAL: {exc}")

    def stop(self, timeout: float = 5.0) -> None:
        if self.voice is not None:
            try:
                self.voice.stop()
            except Exception:
                pass

        self.join(timeout=timeout)

        if self.is_alive():
            print("[launcher] voice runtime did not stop in time")


def _tray_icon() -> "object | None":
    """Build a small purple orb icon for the tray. None if PIL missing."""
    try:
        from PIL import Image, ImageDraw
    except Exception:  # noqa: BLE001
        return None
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=(124, 58, 237, 255))
    d.ellipse((22, 22, 42, 42), fill=(255, 255, 255, 255))
    return img


def run_launcher(
    app=None,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    tray: bool = True,
    enable_voice: bool | None = None,
) -> int:
    """Start the runtime + persistent voice (when enabled).

    This function now delegates to the shared startup path in core.runtime_start.
    """
    from core.runtime_start import start_runtime_and_voice

    if app is None:
        from core.app import AgentApp
        app = AgentApp.create()

    return start_runtime_and_voice(
        app,
        port=port,
        enable_voice=enable_voice,
        open_browser=open_browser,
        tray=tray,
    )


if __name__ == "__main__":
    sys.exit(run_launcher())
