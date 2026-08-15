"""Integration: Task-state continuation.

  "Open YouTube."  →  windows (browser)
  "On my phone."   →  modifies the ACTIVE task → android tool attempted

Task State is persisted and structured (task_state table) — never rebuilt
from the chat transcript. Standalone commands ("brief me") must NOT be
misclassified as continuations.
"""
from __future__ import annotations

import pytest

from database.models import ToolExecution


class _BombProvider:
    name = "bomb"

    async def chat(self, messages, tools=None, session_id=None, on_overflow=None):
        raise AssertionError("LLM consulted for a deterministic task")


def _tools_run(app, session) -> list[str]:
    with app.db.session() as s:
        return [r.tool for r in s.query(ToolExecution)
                .filter_by(session_id=session).order_by(ToolExecution.id).all()]


@pytest.mark.integration
def test_follow_up_switches_target_and_persists_state(app, run_sync):
    app.llm._factory = lambda n, k, m: _BombProvider()
    run_sync(app.orchestrator.handle_user_message("t1", "open youtube"))
    st = app.task_state.get("t1")
    assert st and st["last_goal"] == "open youtube" and st["last_target"] == "windows"

    out = run_sync(app.orchestrator.handle_user_message("t1", "on my phone"))
    st2 = app.task_state.get("t1")
    assert st2["last_goal"] == "open youtube" and st2["last_target"] == "android"
    # the follow-up actually re-ran the task on android (honest offline failure)
    assert "android" in out.lower()
    tools = _tools_run(app, "t1")
    assert "android_open_youtube" in tools


@pytest.mark.integration
def test_no_continuation_without_prior_task(app, run_sync):
    app.llm._factory = lambda n, k, m: _BombProvider()
    # "on my phone" as a FIRST message is not a continuation — it must not
    # crash or fabricate; the orchestrator treats it as its own (unparseable)
    # request and returns a response through the normal path.
    out = run_sync(app.orchestrator.handle_user_message("t2", "on my phone"))
    assert isinstance(out, str) and out
    st = app.task_state.get("t2")
    assert st is None or st["last_goal"] == "on my phone"  # not some ghost goal


@pytest.mark.integration
def test_standalone_commands_not_misclassified(app, run_sync):
    app.llm._factory = lambda n, k, m: _BombProvider()
    run_sync(app.orchestrator.handle_user_message("t3", "open youtube"))
    before = _tools_run(app, "t3").count("browser_open")
    out = run_sync(app.orchestrator.handle_user_message("t3", "brief me"))
    # "brief me" must go to the briefing tool, NOT re-run "open youtube"
    assert "Nothing saved yet" in out
    tools = _tools_run(app, "t3")
    assert "personal_briefing" in tools
    assert tools.count("browser_open") == before  # not re-run


@pytest.mark.integration
def test_task_state_table_is_separate_from_messages(app, run_sync):
    from database.models import Message
    run_sync(app.orchestrator.handle_user_message("t4", "what time is it"))
    st = app.task_state.get("t4")
    assert st["last_goal"] == "what time is it"
    with app.db.session() as s:
        msgs = s.query(Message).filter_by(session_id="t4").count()
    assert msgs >= 1  # transcript exists AND task_state is a separate row
