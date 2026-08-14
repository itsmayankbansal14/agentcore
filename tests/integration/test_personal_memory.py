"""Integration: Personal/Discovery memory.

  "Save this website …" / "Save this idea: …" → structured records in SQLite.
  saved_list / personal_briefing → concise surfaces (never a dump).
  Deterministic commands must NEVER touch the LLM (bomb provider).
"""
from __future__ import annotations

import re

import pytest

from planning.direct import DirectToolRouter


class _BombProvider:
    name = "bomb"

    async def chat(self, messages, tools=None, session_id=None, on_overflow=None):
        raise AssertionError("LLM consulted for a deterministic personal command")


# ---------------------------------------------------------------------------
# router semantics
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_router_save_website_extracts_fields():
    calls = DirectToolRouter().route(
        "save this website https://example.com it's useful for AI research "
        "and I could use it for rapid prototyping")
    assert calls and calls[0][0] == "save_website"
    _, p = calls[0]
    assert p["url"] == "https://example.com"
    assert "AI research" in p["purpose"]
    assert "rapid prototyping" in p["usage"]


@pytest.mark.unit
def test_router_save_idea_extracts_title_keeps_case():
    calls = DirectToolRouter().route("save this idea: build a UPI payment announcer")
    assert calls == [("save_idea", {"title": "build a UPI payment announcer",
                                    "description": ""})]


@pytest.mark.unit
def test_router_save_website_without_url_not_swallowed():
    assert DirectToolRouter().route("save this website") is None


@pytest.mark.unit
def test_router_saved_list_and_briefing():
    r = DirectToolRouter()
    assert r.route("what did i save") == [("saved_list", {})]
    assert r.route("brief me") == [("personal_briefing", {})]


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_save_website_structured_record(app):
    pid = app.personal.save("website", "Example", url="https://example.com",
                            description="useful for AI research",
                            purpose="AI research", usage="rapid prototyping",
                            tags=["ai", "research"])
    rows = app.personal.list(kind="website")
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == pid and r["url"] == "https://example.com"
    assert r["purpose"] == "AI research" and r["usage"] == "rapid prototyping"
    assert "ai" in r["tags"] and r["status"] == "new" and r["created_at"]


@pytest.mark.integration
def test_save_idea_and_filter_by_kind(app):
    app.personal.save("idea", "build a UPI payment announcer")
    app.personal.save("website", "OpenRouter", url="https://openrouter.ai")
    ideas = app.personal.list(kind="idea")
    assert len(ideas) == 1 and ideas[0]["title"] == "build a UPI payment announcer"
    assert app.personal.count() == {"idea": 1, "website": 1}


@pytest.mark.integration
def test_personal_memory_persists_across_app_instances(app):
    app.personal.save("idea", "voice-first desktop agent")
    app.db.close()
    from core.app import AgentApp
    app2 = AgentApp.create(db_path=str(app.db.path))
    try:
        rows = app2.personal.list(kind="idea")
        assert any(r["title"] == "voice-first desktop agent" for r in rows)
    finally:
        app2.db.close()


@pytest.mark.integration
def test_briefing_is_concise_and_surfaces_recent(app):
    app.personal.save("idea", "build a UPI payment announcer")
    app.personal.save("website", "OpenRouter", url="https://openrouter.ai")
    brief = app.personal.briefing()
    assert "UPI" in brief and "OpenRouter" in brief
    assert len(brief) < 400   # concise, never a dump


@pytest.mark.integration
def test_briefing_empty_state_is_helpful(app):
    brief = app.personal.briefing()
    assert "Nothing saved yet" in brief


# ---------------------------------------------------------------------------
# end-to-end through the orchestrator (no LLM)
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_save_commands_via_orchestrator_never_use_llm(app, run_sync):
    app.llm._factory = lambda n, k, m: _BombProvider()
    out1 = run_sync(app.orchestrator.handle_user_message(
        "pm", "save this website https://example.com useful for AI research"))
    assert "Saved website" in out1
    out2 = run_sync(app.orchestrator.handle_user_message(
        "pm", "save this idea: build a UPI payment announcer"))
    assert "Saved idea" in out2
    out3 = run_sync(app.orchestrator.handle_user_message("pm", "what did i save"))
    assert "example.com" in out3 and "UPI" in out3
    out4 = run_sync(app.orchestrator.handle_user_message("pm", "brief me"))
    assert "UPI" in out4 or "example" in out4.lower()


@pytest.mark.integration
def test_saved_list_and_briefing_tools_registered(app):
    for name in ("save_website", "save_idea", "save_note", "saved_list",
                 "personal_briefing"):
        assert app.registry.get(name) is not None, name
