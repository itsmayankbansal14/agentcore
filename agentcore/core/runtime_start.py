"""AgentCore — Shared runtime + voice startup path.

This module provides a single entry point for starting both the
FastAPI/dashboard runtime and the optional persistent voice loop
using the same AgentApp instance.
"""

from __future__ import annotations

import time
import webbrowser
from typing import Optional

from launcher import RuntimeServerThread, VoiceRuntimeThread


def start_runtime_and_voice(
    app,
    *,
    port: int = 8000,
    enable_voice: Optional[bool] = None,
    open_browser: bool = True,
    tray: bool = True,
) -> int:
    """
    Start the shared AgentCore runtime (FastAPI + optional Voice).

    Both the dashboard and voice (when enabled) use the same AgentApp instance.

    Args:
        app: Pre-created AgentApp instance
        port: Port for the FastAPI server
        enable_voice: Whether to start persistent voice.
                      If None, reads from config (voice.enable_on_launch)
        open_browser: Open dashboard in browser
        tray: Enable system tray

    Returns:
        Exit code (0 = success)
    """
    if enable_voice is None:
        try:
            enable_voice = app.config.get_bool("voice.enable_on_launch", True)
        except Exception:
            enable_voice = True

    url = f"http://localhost:{port}"
    print("┌──────────────────────────────────────────────┐")
    print("│  AgentCore — desktop runtime launcher        │")
    print(f"│  dashboard → {url}          │")
    print("└──────────────────────────────────────────────┘")

    runtime = RuntimeServerThread(app=app, port=port)
    runtime.start()

    if not runtime.wait_until_ready():
        print("[launcher] ❌ runtime failed to start (is the port busy?)")
        return 1
    print(f"[launcher] ✅ runtime ready → {url}")

    voice_runtime = None
    if enable_voice:
        voice_runtime = VoiceRuntimeThread(app)
        voice_runtime.start()
        print("[launcher] voice runtime starting…")

    if open_browser:
        try:
            webbrowser.open(url)
            print("[launcher] opened dashboard in your default browser")
        except Exception:
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
        except Exception:
            pystray = None
        if pystray is not None:
            from launcher import _tray_icon
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
            icon.run()
            stop_all()
            print("[launcher] stopped cleanly")
            return 0

    print("[launcher] running in console mode — press Ctrl+C to stop")
    try:
        while runtime.is_alive() or (voice_runtime and voice_runtime.is_alive()):
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[launcher] Ctrl+C received — shutting down…")

    stop_all()
    print("[launcher] stopped cleanly")
    return 0