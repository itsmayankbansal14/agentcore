"""AgentCore — dashboard/app.py
PRIMARY development entry point (thin presentation layer).

  python main.py                → boots THIS app at http://localhost:8000
  python dashboard/app.py       → same

This dashboard is a development console, NOT business logic. It talks ONLY
through AgentApp's public API (orchestrator / planner / memory / executor /
devices / registry — all reachable via the agent instance), and renders the
HTML template at dashboard/templates/dashboard.html. No tool logic, no
planning, no provider code lives here.
"""
from __future__ import annotations

import os
from pathlib import Path

from core.app import AgentApp

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "templates" / "dashboard.html"

DEFAULT_PORT = 8000


def create_app(agent: AgentApp | None = None):
    """Build the dashboard FastAPI app over AgentApp's public API."""
    from api.server import create_app as build_base

    agent_app = agent or AgentApp.create()
    app = build_base(agent_app, template=TEMPLATE if TEMPLATE.exists() else None)
    return app


def run(agent: AgentApp | None = None, host: str = "0.0.0.0",
        port: int | None = None) -> None:
    """Run the dashboard server (used by `python main.py` / `python dashboard/app.py`)."""
    import uvicorn
    port = port or int(os.environ.get("AGENTCORE_PORT", DEFAULT_PORT))
    print(f"🖥️  AgentCore dev console → http://localhost:{port}")
    uvicorn.run(create_app(agent), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run()
