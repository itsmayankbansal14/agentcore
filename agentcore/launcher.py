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

            # Use dedicated event loop for async voice loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.voice.run_loop_async())
            finally:
                loop.close()

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


def start_runtime_and_voice(
    app,
    port: int = DEFAULT_PORT,
    enable_voice: bool | None = None,
) -> tuple[RuntimeServerThread, VoiceRuntimeThread | None]:
    """Start the shared runtime server and optional voice runtime.
    Returns (runtime_thread, voice_thread_or_None).
    Caller is responsible for stopping threads and handling browser/tray/console.
    """
    # Read from config if not explicitly passed
    if enable_voice is None:
        try:
            enable_voice = app.config.get_bool("voice.enable_on_launch", False)
        except Exception:
            enable_voice = False

    runtime = RuntimeServerThread(app=app, port=port)
    runtime.start()

    if not runtime.wait_until_ready():
        print("[launcher] ❌ runtime failed to start (is the port busy?)")
        runtime.stop()
        raise RuntimeError("Runtime failed to start")

    print(f"[launcher] ✅ runtime ready → http://localhost:{port}")

    voice_runtime = None
    if enable_voice:
        voice_runtime = VoiceRuntimeThread(app)
        voice_runtime.start()
        print("[launcher] voice runtime starting…")

        # Give voice a moment to initialize and report status
        time.sleep(1.8)
        if voice_runtime and voice_runtime.error:
            print("\n[launcher] ⚠ VOICE: FAILED")
            print(f"[launcher] Voice error: {voice_runtime.error}")
            print("[launcher] Dashboard/runtime will continue without voice.\n")
            voice_runtime = None  # Prevent shutdown logic from trying to stop it

    return runtime, voice_runtime


def run_launcher(
    app=None,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    tray: bool = True,
    enable_voice: bool | None = None,   # Phase 4: Can be overridden
) -> int:
    """Start the runtime + (optionally) persistent voice, open the dashboard, keep alive."""
    if app is None:
        from core.app import AgentApp
        app = AgentApp.create()

    url = f"http://localhost:{port}"
    print("┌──────────────────────────────────────────────┐")
    print("│  AgentCore — desktop runtime launcher        │")
    print(f"│  dashboard → {url}          │")
    print("└──────────────────────────────────────────────┘")

    runtime, voice_runtime = start_runtime_and_voice(app, port, enable_voice)

    if open_browser:
        try:
            webbrowser.open(url)
            print("[launcher] opened dashboard in your default browser")
        except Exception:  # noqa: BLE001
            print("[launcher] could not open browser — visit manually:", url)

    def stop_all():
        if voice_runtime is not None:
            try:
                voice_runtime.stop()
            except Exception:
                pass
        runtime.stop()

    if tray:
        try:
            import pystray
            from pystray import Menu, MenuItem
        except Exception:  # noqa: BLE001
            pystray = None
        if pystray is not None:
            img = _tray_icon()
            icon = pystray.Icon(
                "agentcore",
                img or __import__("PIL").Image.new("RGBA", (1, 1), (124, 58, 237, 255)),
                "AgentCore",
                Menu(
                    MenuItem("Open Dashboard", lambda: webbrowser.open(url)),
                    MenuItem("Stop AgentCore", lambda: (stop_all(), icon.stop())),
                ),
            )
            print("[launcher] running in system tray — right-click the icon to stop")
            icon.run()          # blocks until icon.stop()
            stop_all()
            print("[launcher] stopped cleanly")
            return 0

    # no tray → console mode
    print("[launcher] running in console mode — press Ctrl+C to stop")
    try:
        while runtime.is_alive() or (voice_runtime and voice_runtime.is_alive()):
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[launcher] Ctrl+C received — shutting down…")

    stop_all()
    print("[launcher] stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(run_launcher())
