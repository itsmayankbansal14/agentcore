"""AgentCore — tests/integration/conftest.py
Shared fixtures for the integration suite. Every integration test runs
against the REAL AgentApp runtime: real AgentApp.create(), real Planner /
Executor / Tool registry / Observer / Memory / SQLite — only the LLM is
pinned to a deterministic mock (router keys are hermetic per test), because
integration tests must not depend on external API availability.
"""
from __future__ import annotations

import tempfile

import pytest

from core.app import AgentApp
from llm.router import KeyRuntime


@pytest.fixture()
def app():
    """A fresh AgentApp runtime with a hermetic (mock) LLM provider."""
    a = AgentApp.create(db_path=tempfile.mktemp(suffix=".db"))
    a.llm.router.keys = [KeyRuntime("mock", "mock-key", "mock-1")]
    yield a
    try:
        a.db.close()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture()
def session(app):
    """A guaranteed session row in the runtime DB."""
    app.orchestrator.ensure_session("it")
    return "it"


@pytest.fixture()
def run_sync():
    """Run an async coroutine synchronously (pytest-asyncio not required)."""
    import asyncio

    def _run(coro):
        return asyncio.run(coro)

    return _run


@pytest.fixture()
def mock_llm(app):
    """Scriptable mock provider wired as the runtime's LLM."""
    from llm.providers import MockProvider
    mp = MockProvider()
    app.llm._factory = lambda n, k, m: mp
    return mp
