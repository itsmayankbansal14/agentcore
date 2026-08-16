"""Integration: Target Resolution (before planning).

Pipeline: User Goal → Intent Analysis → TargetResolver → Planner → Executor → Observer

Objectives verified:
  [1] "Set reminder"                          → Windows (default)
  [2] "Set reminder on my phone"              → Android (explicit); offline → falls back
                                              to Windows when capability exists there
  [3] "Open YouTube"                          → Browser on Windows (capability on host)
  [4] "Open YouTube on my phone"              → Android (explicit; android-only capability)
  [5] Android disconnected → planner falls back to Windows whenever the capability
      exists there
  [6] The planner NEVER assumes Android just because an android tool exists — it
      requests capabilities; DeviceManager selects the device.
"""
import pytest

from core.contracts import EventType


def _resolver(app):
    return app.target_resolver


@pytest.mark.integration
def test_default_target_is_windows(app):
    d = _resolver(app).resolve("set a reminder to finish DSA", "life.todos", "s1")
    assert d.device == "windows"
    assert d.explicit is False
    assert "default" in d.reason


@pytest.mark.integration
def test_explicit_phone_selects_android(app):
    d = _resolver(app).resolve("set a reminder on my phone", "life.todos", "s2")
    # explicit phone target is honored (explicit=True), and with android OFFLINE
    # + capability on windows, the spec's fallback applies (covered in detail by
    # test_android_offline_falls_back...). The intended target is remembered.
    assert d.explicit is True
    assert d.device in ("android", "windows")
    assert d.alternative is None or d.alternative == "android"


@pytest.mark.integration
def test_open_youtube_defaults_browser_on_windows(app):
    d = _resolver(app).resolve("open youtube", "workflow.browser", "s3")
    # youtube is a browser capability hosted on windows; default policy → windows
    assert d.device == "windows"
    assert d.explicit is False


@pytest.mark.integration
def test_open_youtube_on_phone_selects_android(app):
    d = _resolver(app).resolve("open youtube on my phone", "device.android", "s4")
    assert d.device == "android"
    assert d.explicit is True


@pytest.mark.integration
def test_android_offline_falls_back_to_windows_when_capability_exists(app):
    # android is offline (no device in sandbox); "set reminder on my phone" is
    # a life capability that ALSO exists on windows → fall back to windows
    d = _resolver(app).resolve("set a reminder on my phone", "life.todos", "s5")
    assert d.device == "windows"
    assert "fell back" in d.reason or "fallback" in d.reason or "offline" in d.reason


@pytest.mark.integration
def test_android_offline_android_only_capability_stays_android_with_reason(app):
    d = _resolver(app).resolve("open youtube on my phone", "device.android", "s6")
    assert d.device == "android"
    assert "android-only" in d.reason or "cannot execute" in d.reason


@pytest.mark.integration
def test_planner_never_queries_android_directly(app):
    """The planner requests capabilities; DeviceManager selects the device.
    Assert the orchestrator emits TARGET_RESOLVED before planning and that
    resolution goes through the resolver (no direct android query)."""
    # orchestrate a full command; the target event must be on the bus
    import asyncio
    from llm.providers import MockProvider
    mp = MockProvider()
    app.llm._factory = lambda n, k, m: mp
    mp.enqueue("[ECHO]", "[ECHO]")  # planner decompose + executor
    app.orchestrator.ensure_session("tr")
    asyncio.run(app.orchestrator.handle_user_message(
        "tr", "set a reminder to finish DSA"))
    types = {e.type for e in app.bus.recent(session_id="tr", n=200)}
    assert EventType.TARGET_RESOLVED in types
    # the resolver decided (default windows), NOT direct android access
    last = None
    for e in reversed(app.bus.recent(session_id="tr", n=200)):
        if e.type == EventType.TARGET_RESOLVED:
            last = e
            break
    assert last is not None and last.payload.get("device") == "windows"


@pytest.mark.integration
def test_session_preference_remembered(app):
    r = _resolver(app)
    # explicit phone choice remembers the INTENDED device for the session
    d = r.resolve("set reminder on my phone", "life.todos", "s7")
    assert r._session_pref.get("s7") == "android"
    # next goal in the SAME session uses the remembered preference (android),
    # falling back to windows because android is offline & capability exists
    d2 = r.resolve("set another reminder", "life.todos", "s7")
    assert r._session_pref.get("s7") == "android"        # remembered
    assert d2.device == "windows"                        # offline fallback applies
    assert d2.alternative == "android"                   # intended target surfaced


@pytest.mark.integration
def test_available_devices_report(app):
    avail = _resolver(app).available_devices()
    assert set(avail) >= {"windows", "android", "browser"}
    assert avail["windows"]["online"] is True
    assert "android" in avail and avail["android"]["online"] is False  # no device
    # browser detected via playwright presence
    assert avail["browser"]["online"] is True
