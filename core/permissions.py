"""AgentCore — core/permissions.py
PermissionManager. Every tool call is classified before execution:
  ALLOWED (auto) · CONFIRM_REQUIRED (ask user) · DENIED (blocked)

Policy sources (most specific wins):
  1. config `tools.allowlist` / `tools.denylist` (tool names / capabilities)
  2. tool's declared `permission` level (ALWAYS / USER_CONFIRM / ADMIN)
  3. global default
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from config.manager import ConfigManager
from core.contracts import Permission, ToolSpec


class Decision(str, Enum):
    ALLOWED = "allowed"
    CONFIRM_REQUIRED = "confirm_required"
    DENIED = "denied"


@dataclass
class PermissionResult:
    decision: Decision
    reason: str = ""
    tool: str = ""


class PermissionManager:
    def __init__(self, config: ConfigManager,
                 confirm_callback: Callable[[str, dict], bool] | None = None) -> None:
        self.cfg = config
        self.confirm_callback = confirm_callback  # UI/CLI hook: ask the user

    def classify(self, spec: ToolSpec | None, tool_name: str,
                 args: dict | None = None) -> PermissionResult:
        args = args or {}
        allowlist = self.cfg.get_list("tools.allowlist", [])
        denylist = self.cfg.get_list("tools.denylist", [])

        # deny wins
        if tool_name in denylist or (spec and spec.capability in denylist):
            return PermissionResult(Decision.DENIED, f"{tool_name} is denied by policy", tool_name)
        # explicit allowlist
        if allowlist and (tool_name in allowlist or (spec and spec.capability in allowlist)):
            return PermissionResult(Decision.ALLOWED, "allowlisted", tool_name)

        # fall back to the tool's declared permission level
        if spec is None:
            return PermissionResult(Decision.DENIED, f"unknown tool {tool_name}", tool_name)
        if spec.permission == Permission.ALWAYS:
            return PermissionResult(Decision.ALLOWED, "always-allowed tool", tool_name)
        if spec.permission == Permission.ADMIN:
            return PermissionResult(Decision.CONFIRM_REQUIRED, "admin-level tool", tool_name)
        # USER_CONFIRM
        if self.confirm_callback is not None:
            ok = self.confirm_callback(tool_name, args)
            return PermissionResult(Decision.ALLOWED if ok else Decision.DENIED,
                                    "user confirm" if ok else "user denied", tool_name)
        return PermissionResult(Decision.CONFIRM_REQUIRED, "confirmation required", tool_name)

    def check(self, spec: ToolSpec | None, tool_name: str,
              args: dict | None = None) -> PermissionResult:
        """Stateless check (no callback invoked)."""
        result = self.classify(spec, tool_name, args)
        # downgrade CONFIRM_REQUIRED to DENIED when there's no callback to ask
        if result.decision == Decision.CONFIRM_REQUIRED and self.confirm_callback is None:
            return PermissionResult(Decision.DENIED,
                                    "confirmation required but no UI to ask", tool_name)
        return result
