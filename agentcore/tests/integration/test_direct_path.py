"""Integration: deterministic fast-path (planning/direct.py) + new tools.

Pipeline: User Goal → DirectToolRouter → real tool (NO LLM) → observer → memory.

Verified:
  [1] time / todo / clipboard / open-youtube route to their real tools and the
      LLM is NEVER consulted (a bomb provider raises if it is)
  [2] complex multi-intent goals are NOT swallowed by the direct path
  [3] "open youtube" → browser (windows); "…on my phone" → android tool
  [4] clipboard tools are registered and fail honestly without a clipboard
  [5] weather tool returns REAL data via Open-Meteo when the network is up
"""
from __future__ import annotations

import re

import pytest

from planning.direct import DirectToolRouter


class _BombProvider:
    """Raises if the executor ever consults the LLM."""
    name = "bomb"

    async def chat(self, messages, tools=None, session_id=None, on_overflow=None):
        raise AssertionError("LLM consulted for a deterministic request")


# ---------------------------------------------------------------------------
# router unit semantics
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_router_time():
    assert DirectToolRouter().route("what time is it?") == [("time_now", {})]
    assert DirectToolRouter().route("current time") == [("time_now", {})]


@pytest.mark.unit
def test_router_weather_city_extraction():
    # city is lowercased by the router; Open-Meteo geocodes case-insensitively
    assert DirectToolRouter().route("weather in Jaipur") == [("weather", {"city": "jaipur"})]


@pytest.mark.unit
def test_router_todo_add_and_list():
    calls = DirectToolRouter().route("add todo finish DSA high priority")
    assert calls and calls[0][0] == "todo_add"
    _, params = calls[0]
    assert params["task"] == "finish dsa" and params["priority"] == "high"
    assert DirectToolRouter().route("list my todos") == [("todo_list", {})]


@pytest.mark.unit
def test_router_youtube_device():
    r = DirectToolRouter()
    assert r.route("open youtube", "windows")[0][0] == "browser_open"
    assert r.route("open youtube", "windows")[1][0] == "browser_navigate"
    assert r.route("open youtube on my phone", "android") == [("android_open_youtube", {"query": ""})]
    # explicit phone marker wins even without resolved target
    assert r.route("open youtube on my android phone", "windows") == [("android_open_youtube", {"query": ""})]


@pytest.mark.unit
def test_router_never_swallows_complex_goals():
    r = DirectToolRouter()
    for goal in ("wake, unlock, open youtube, wait, screenshot and verify on my phone",
                 "open youtube then play lofi",
                 "what is the time and date",
                 "hello there",
                 "what is the capital of France"):
        assert r.route(goal) is None, goal


@pytest.mark.unit
def test_router_clipboard_set_get():
    r = DirectToolRouter()
    assert r.route("copy hello world") == [("clipboard_set", {"text": "hello world"})]
    assert r.route("set clipboard to abc") == [("clipboard_set", {"text": "abc"})]
    assert r.route("what's on my clipboard") == [("clipboard_get", {})]


# ---------------------------------------------------------------------------
# end-to-end: deterministic goals never touch the LLM
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_direct_path_time_never_calls_llm(app, session, run_sync):
    app.llm._factory = lambda n, k, m: _BombProvider()
    out = run_sync(app.orchestrator.handle_user_message(session, "what time is it?"))
    assert re.search(r"\d{1,2}:\d{2}", out), out
    assert "bomb" not in out.lower()  # the LLM was never consulted


@pytest.mark.integration
def test_direct_path_todo_never_calls_llm_and_persists(app, session, run_sync):
    app.llm._factory = lambda n, k, m: _BombProvider()
    out = run_sync(app.orchestrator.handle_user_message(
        session, "add todo finish DSA high priority"))
    assert "Added todo" in out
    from database.models import ToolExecution
    with app.db.session() as s:
        row = s.query(ToolExecution).filter_by(session_id=session,
                                               tool="todo_add").first()
    assert row is not None and row.status == "ok"


@pytest.mark.integration
def test_clipboard_tools_registered(app):
    for name in ("clipboard_set", "clipboard_get"):
        assert app.registry.get(name) is not None, name
        assert app.registry.get(name).capability == "clipboard"


@pytest.mark.integration
def test_clipboard_set_honest_failure_on_headless(app, run_sync):
    """On a machine without a clipboard the tool must return a structured
    error — never a fake success."""
    tool = app.registry.get("clipboard_set")
    res = run_sync(tool.execute({"text": "x"}, {"session_id": "t"}))
    if res.ok:  # real desktop clipboard present (e.g. Windows)
        assert res.data.get("set") is True
    else:       # headless/SSH — must fail loudly, not silently
        assert "clipboard" in (res.error or "").lower()


@pytest.mark.integration
def test_weather_tool_real_or_honest_failure(app, run_sync):
    tool = app.registry.get("weather")
    res = run_sync(tool.execute({"city": "Jaipur"}, {"session_id": "t"}))
    if res.ok:
        # real data (Open-Meteo), never the old random mock
        assert res.data.get("source") == "open-meteo"
        assert res.data.get("temp_c") is not None
    else:
        assert "weather" in (res.error or "").lower()


@pytest.mark.integration
def test_open_youtube_on_phone_honest_when_offline(app, session, run_sync):
    """Deterministic intent routes to the android tool; with no device it
    fails truthfully (never pretends the phone opened YouTube)."""
    app.llm._factory = lambda n, k, m: _BombProvider()
    out = run_sync(app.orchestrator.handle_user_message(
        session, "open youtube on my phone"))
    if "📱" in out:
        return  # a real device responded
    assert "failed" in out.lower() and "android" in out.lower(), out
    from database.models import ToolExecution
    with app.db.session() as s:
        row = s.query(ToolExecution).filter_by(session_id=session,
                                               tool="android_open_youtube").first()
    assert row is not None
