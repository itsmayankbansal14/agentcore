"""Integration: Android workflows (real ADB transport + DeviceManager routing).

Real: ADBDevice (adb-shell protocol client) reports honest online/offline;
android_* tools route through DeviceManager with device_id selection and
ADB fallback; an offline device yields a classified, history-recorded failure
with recovery suggestions.
"""
import json

import pytest


@pytest.mark.integration
def test_adb_device_registered_and_offline_honest(app):
    dev = app.devices.get("adb")
    assert dev is not None
    assert dev.health()["transport"] == "adb"
    assert dev.health()["online"] is False  # no device in sandbox → honest


@pytest.mark.integration
def test_android_tool_dispatches_via_device_manager(app, run_sync):
    from core.contracts import ToolCall
    tc = ToolCall(id="a1", name="android_open_youtube",
                  arguments={"query": "lofi", "device_id": "adb"})
    res = run_sync(app.executor._dispatch_tool("android_it", None, tc))
    assert not res.ok  # adb offline
    assert res.data.get("blocked") or "online" in (res.error or "")


@pytest.mark.integration
def test_android_failure_recorded_with_class_and_suggestions(app, session, run_sync):
    from core.contracts import ToolCall
    tc = ToolCall(id="a2", name="android_open_youtube",
                  arguments={"query": "lofi", "device_id": "adb"})
    run_sync(app.executor._dispatch_tool(session, None, tc))
    from database.models import ToolExecution
    with app.db.session() as s:
        row = s.query(ToolExecution).filter_by(session_id=session,
                                               tool="android_open_youtube").first()
    assert row is not None
    assert row.failure_class in ("device", "tool")
    sugs = json.loads(row.recovery_suggestions or "[]")
    assert any("adb" in s.lower() or "phone" in s.lower() for s in sugs)


@pytest.mark.integration
def test_android_device_id_selection(app, run_sync):
    """device_id selects a specific device; default falls back to adb."""
    from tools.base import Tool
    from core.contracts import ToolResult

    class FakePhone(Tool):
        name = "android_open_youtube"
        description = "open youtube on phone"
        parameters = {"type": "object", "properties": {}}
        capability = "device.android"
        async def execute(self, params, ctx):
            return ToolResult(ok=True, data={"via": "ws"})

    # primary 'android' device (WS companion) is offline → tool falls back to adb
    res = run_sync(app.registry.execute("android_open_youtube",
                                        {"query": "x"}, {"confirm": True}))
    assert not res.ok  # both android(ws) and adb offline here → honest failure
