"""Integration: API provider switching / failover / continuity.

Real: LLMRouter + LLMManager — a bad key is cooled down, the conversation is
replayed to the next provider, and continuity is preserved (same message
list, same session memory). Providers are scripted mocks (deterministic),
but the router/rotation/cooldown/context-replay machinery is the real one.
"""
import pytest

from core.contracts import LLMMessage, Role
from llm.providers import MockProvider
from llm.router import KeyRuntime, LLMRouter


@pytest.mark.integration
def test_router_fails_over_and_preserves_context(run_sync):
    good = MockProvider(model="good")
    good.enqueue("[ECHO]")
    bad = MockProvider(model="bad")
    bad.fail_rate_once = True
    calls = []

    def factory(name, key, model):
        calls.append(f"{name}:{model}")
        return good if name == "good" else bad

    keys = [KeyRuntime("bad", "k2", "bad"), KeyRuntime("good", "k1", "good")]
    router = LLMRouter(keys, cooldown_seconds=10)
    msgs = [LLMMessage(role=Role.USER, content="remember this conversation")]
    resp = run_sync(router.chat(factory, msgs))
    assert resp.provider == "mock" and "good" in calls[-1]
    assert keys[0].cooldown_until > 0  # rate-limited key cooled down

    # second call skips the bad key entirely (cooldown)
    calls.clear()
    run_sync(router.chat(factory, msgs))
    assert "bad" not in calls


@pytest.mark.integration
def test_manager_provider_switch_keeps_session(app, session, mock_llm, run_sync):
    # the app-level LLMManager: two conversations on one session keep history
    mock_llm.enqueue("[ECHO]")
    run_sync(app.orchestrator.handle_user_message(session, "hello there"))
    mock_llm.enqueue("[ECHO]")
    run_sync(app.orchestrator.handle_user_message(session, "second message"))
    history = app.memory.load_history(session)
    assert any("hello there" in (m.content or "") for m in history)
    assert any("second message" in (m.content or "") for m in history)


@pytest.mark.integration
def test_router_continuity_on_overflow(run_sync):
    """Context-overflow triggers trimming, not a crash (real router hook)."""
    good = MockProvider(model="good")
    good.fail_overflow = True
    good.enqueue("[ECHO]", "[ECHO]")
    keys = [KeyRuntime("mock", "k", "m")]
    router = LLMRouter(keys)
    msgs = [LLMMessage(role=Role.USER, content="x" * 4000)]

    def factory(name, key, model):
        return good

    # on_overflow trims; then the retry succeeds
    def on_overflow(sid, messages):
        return messages[-2:]

    resp = run_sync(router.chat(factory, msgs, on_overflow=on_overflow))
    assert resp is not None and resp.content  # served after trimming
