"""AgentCore — tools/registry.py
Searchable tool registry (per critique: no hardcoded keyword dispatch).
tool.search(query) lets the planner/LLM discover only relevant tools;
capability routing lets a logical call land on whichever device serves it.
"""
from __future__ import annotations

import structlog
from difflib import SequenceMatcher
from typing import Any

from core.contracts import ToolResult, ToolSpec
from core.permissions import Decision, PermissionManager
from tools.base import Tool

log = structlog.get_logger("agentcore.tools")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._capabilities: dict[str, list[str]] = {}  # capability -> tool names

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool
        self._capabilities.setdefault(tool.capability, []).append(tool.name)
        log.info("tool registered", name=tool.name, capability=tool.capability)

    def unregister(self, name: str) -> None:
        tool = self._tools.pop(name, None)
        if tool:
            self._capabilities[tool.capability] = [
                n for n in self._capabilities.get(tool.capability, []) if n != name]

    # -- lookup ------------------------------------------------------------
    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_spec(self, name: str) -> ToolSpec | None:
        t = self._tools.get(name)
        return t.spec() if t else None

    def specs(self, names: list[str] | None = None) -> list[ToolSpec]:
        if names is None:
            names = list(self._tools)
        return [self._tools[n].spec() for n in names if n in self._tools]

    def search(self, query: str, top_k: int = 8) -> list[ToolSpec]:
        """Score tools by keyword overlap in name/desc/capability."""
        q = query.lower()
        scored: list[tuple[float, ToolSpec]] = []
        for tool in self._tools.values():
            hay = f"{tool.name} {tool.description} {tool.capability}".lower()
            score = 0.0
            for word in q.split():
                if word in tool.name:
                    score += 3.0
                if word in hay:
                    score += 1.0
            # fuzzy similarity on the query vs name+capability
            score += SequenceMatcher(None, q, tool.name).ratio()
            if score > 0:
                scored.append((score, tool.spec()))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:top_k]]

    def for_capability(self, capability: str) -> list[ToolSpec]:
        return [self._tools[n].spec() for n in self._capabilities.get(capability, [])]

    # -- execution ---------------------------------------------------------
    async def execute(self, name: str, params: dict[str, Any],
                      ctx: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, error=f"unknown tool: {name}", tool=name)
        # permission gate: Allowed / Confirm required / Denied
        perms: PermissionManager | None = ctx.get("permissions")
        if perms is not None:
            result = perms.check(tool.spec(), name, params)
            if result.decision == Decision.DENIED:
                return ToolResult(ok=False, error=f"permission denied: {result.reason}", tool=name)
            if result.decision == Decision.CONFIRM_REQUIRED:
                return ToolResult(ok=False,
                                  error=f"confirmation required: {result.reason}", tool=name,
                                  data={"needs_confirm": True})
        return await tool.guarded_execute(params, ctx)

    def __len__(self) -> int:
        return len(self._tools)
