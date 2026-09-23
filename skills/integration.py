"""Integration helpers to wire OpenJarvis skill system into AgentCore.

This module bridges SkillExecutor with AgentCore ToolRegistry and PermissionManager,
so skills run through Planner → Executor → PermissionManager → ToolRegistry → Observer.
"""

from __future__ import annotations

from typing import Any, Dict

from skills.types import SkillManifest
from skills.executor import SkillExecutor, SkillResult
from skills.catalog import SkillCatalog
from pathlib import Path


def make_tool_executor(registry, permissions=None):
    """Return a callable usable by SkillExecutor that respects AgentCore tool registry
    and PermissionManager.

    Args:
        registry: tools.registry.ToolRegistry instance
        permissions: core.permissions.PermissionManager instance or None
    """
    def _exec(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        # Permission check via registry context
        ctx = {"permissions": permissions}
        # registry.execute returns core.contracts.ToolResult? adapt
        res = registry.execute(tool_name, params, ctx)
        # Normalize to dict for executor
        if hasattr(res, "ok"):
            return {"ok": bool(res.ok), "data": getattr(res, "data", None), "error": getattr(res, "error", None), "tool": tool_name}
        return {"ok": False, "error": f"unknown result", "data": None, "tool": tool_name}
    return _exec


def make_skill_resolver(catalog: SkillCatalog, registry, permissions=None):
    """Return SkillResolver that runs sub-skills through the same executor pipeline."""
    executor = SkillExecutor(make_tool_executor(registry, permissions))
    # recursive resolver
    def _resolve(name: str, ctx: Dict[str, Any]) -> SkillResult:
        manifest = catalog.get(name)
        if manifest is None:
            return SkillResult(skill_name=name, success=False, context=ctx)
        # allow sub-calls to invoke further skills
        executor.set_skill_resolver(_resolve)
        return executor.run(manifest, initial_context=ctx)
    return _resolve


def run_skill_by_name(name: str, catalog_paths: list[Path], registry, permissions=None, initial_context: Dict[str, Any] | None = None) -> SkillResult:
    catalog = SkillCatalog(catalog_paths)
    manifest = catalog.get(name)
    if manifest is None:
        return SkillResult(skill_name=name, success=False)
    resolver = make_skill_resolver(catalog, registry, permissions)
    executor = SkillExecutor(make_tool_executor(registry, permissions))
    executor.set_skill_resolver(resolver)
    return executor.run(manifest, initial_context=initial_context)


__all__ = ["make_tool_executor", "make_skill_resolver", "run_skill_by_name"]
