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
    """Runs the shared AgentCore runtime (FastAPI) in a dedicated thread.

    Uses dashboard.app.create_app — the SAME factory as development mode —
    so the desktop app, web dashboard, Android client, CLI and voice all
    talk to one runtime."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 log_level: str = "warning") -> None:
        super().__init__(daemon=True, name="agentcore-runtime")
        self.host = host
        self.port = port
        self.log_level = log_level
        self.server = None

    def run(self) -> None:
        import uvicorn
        from dashboard.app import create_app
        self.server = uvicorn.Server(uvicorn.Config(
            create_app(), host=self.host, port=self.port, log_level=self.log_level))
        self.server.run()   # blocks until should_exit

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


def run_launcher(port: int = DEFAULT_PORT, open_browser: bool = True,
                 tray: bool = True) -> int:
    """Start the runtime, open the dashboard, keep alive (tray or console)."""
    url = f"http://localhost:{port}"
    print("┌──────────────────────────────────────────────┐")
    print("│  AgentCore — desktop runtime launcher        │")
    print(f"│  dashboard → {url}          │")
    print("└──────────────────────────────────────────────┘")

    runtime = RuntimeServerThread(port=port)
    runtime.start()

    if not runtime.wait_until_ready():
        print("[launcher] ❌ runtime failed to start (is the port busy?)")
        return 1
    print(f"[launcher] ✅ runtime ready → {url}")

    if open_browser:
        try:
            webbrowser.open(url)
            print("[launcher] opened dashboard in your default browser")
        except Exception:  # noqa: BLE001
            print("[launcher] could not open browser — visit manually:", url)

    stop_cb = lambda: runtime.stop()  # noqa: E731

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
                    MenuItem("Stop AgentCore", lambda: (stop_cb(), icon.stop())),
                ),
            )
            print("[launcher] running in system tray — right-click the icon to stop")
            icon.run()          # blocks until icon.stop()
            runtime.stop()
            print("[launcher] stopped cleanly")
            return 0

    # no tray → console mode
    print("[launcher] running in console mode — press Ctrl+C to stop")
    try:
        while runtime.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[launcher] Ctrl+C received — shutting down…")
    runtime.stop()
    print("[launcher] stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(run_launcher())
