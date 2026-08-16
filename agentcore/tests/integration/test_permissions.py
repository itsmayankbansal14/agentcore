"""Integration: Permission system (Allowed / Confirm / Denied) at runtime.

Real: PermissionManager + the ToolRegistry gate — every tool execution is
classified; denylist blocks; confirm-required without a UI denies; the agent
loop respects the gate (a denied tool fails with a permission error, not by
executing).
"""
import pytest

from core.contracts import Permission, ToolSpec
from core.permissions import Decision, PermissionManager


@pytest.mark.integration
def test_permission_gate_on_registry(app, run_sync):
    # a USER_CONFIRM tool with no confirm UI → DENIED at execution
    from core.contracts import ToolResult
    from tools.base import Tool

    class Risky(Tool):
        name = "it_risky"
        description = "needs confirmation"
        parameters = {"type": "object", "properties": {}}
        permission = Permission.USER_CONFIRM
        ran = False
        async def execute(self, params, ctx):
            Risky.ran = True
            return ToolResult(ok=True, data={})

    app.registry.register(Risky())
    ctx = {"confirm": True, "permissions": app.permissions}
    res = run_sync(app.registry.execute("it_risky", {}, ctx))
    assert not res.ok and "permission" in (res.error or "").lower()
    assert Risky.ran is False  # never executed


@pytest.mark.integration
def test_denylist_blocks_tool(app, run_sync):
    from core.contracts import ToolResult
    from tools.base import Tool

    class Blocked(Tool):
        name = "it_blocked"
        description = "should be denied by config"
        parameters = {"type": "object", "properties": {}}
        ran = False
        async def execute(self, params, ctx):
            Blocked.ran = True
            return ToolResult(ok=True, data={})

    app.registry.register(Blocked())
    app.config.set_runtime("tools.denylist", ["it_blocked"])
    ctx = {"confirm": True, "permissions": app.permissions}
    res = run_sync(app.registry.execute("it_blocked", {}, ctx))
    assert not res.ok and "denied" in (res.error or "").lower()
    assert Blocked.ran is False


@pytest.mark.integration
def test_permission_classification_matrix():
    pm = PermissionManager(__import__("config.manager", fromlist=["ConfigManager"]).ConfigManager())
    always = ToolSpec(name="t", description="", parameters={},
                      permission=Permission.ALWAYS)
    confirm = ToolSpec(name="c", description="", parameters={},
                       permission=Permission.USER_CONFIRM)
    assert pm.check(always, "t").decision == Decision.ALLOWED
    assert pm.check(confirm, "c").decision == Decision.DENIED  # no UI → denied
    pm2 = PermissionManager(pm.cfg, confirm_callback=lambda n, a: True)
    assert pm2.check(confirm, "c").decision == Decision.ALLOWED
