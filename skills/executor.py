"""SkillExecutor — run skill steps sequentially.

Adapted from OpenJarvis src/openjarvis/skills/executor.py
Apache-2.0
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from skills.types import SkillManifest
from skills.security import validate_capabilities


@dataclass(slots=True)
class SkillResult:
    skill_name: str = ""
    success: bool = True
    step_results: List[Any] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


SkillResolver = Callable[[str, Dict[str, Any]], SkillResult]


class SkillExecutor:
    def __init__(
        self,
        tool_executor: Callable[[str, Dict[str, Any]], Any],
        *,
        allowed_capabilities: Optional[Set[str]] = None,
    ):
        self._tool_executor = tool_executor
        self._skill_resolver: Optional[SkillResolver] = None
        self._allowed_capabilities = allowed_capabilities

    def set_skill_resolver(self, resolver: SkillResolver) -> None:
        self._skill_resolver = resolver

    def run(self, manifest: SkillManifest, *, initial_context: Optional[Dict[str, Any]] = None) -> SkillResult:
        if self._allowed_capabilities is not None:
            missing = validate_capabilities(manifest, self._allowed_capabilities)
            if missing:
                return SkillResult(
                    skill_name=manifest.name,
                    success=False,
                    step_results=[],
                    context=dict(initial_context or {}),
                )
        ctx = dict(initial_context or {})
        all_results = []
        for i, step in enumerate(manifest.steps):
            template = step.arguments_template
            rendered = self._render_template(template, ctx)
            try:
                args = json.loads(rendered)
            except json.JSONDecodeError:
                args = {}
            if step.skill_name:
                if self._skill_resolver is None:
                    return SkillResult(skill_name=manifest.name, success=False, step_results=all_results, context=ctx)
                result = self._skill_resolver(step.skill_name, {**ctx, **args})
                all_results.append(result)
                if not result.success:
                    break
                if step.output_key:
                    ctx[step.output_key] = result.context.get(step.output_key, "")
            else:
                tool_name = step.tool_name
                try:
                    res = self._tool_executor(tool_name, args)
                except Exception as e:
                    res = {"ok": False, "error": str(e), "data": None, "tool": tool_name}
                all_results.append(res)
                if not res.get("ok", True):
                    break
                if step.output_key:
                    ctx[step.output_key] = res.get("data")
        success = all(r.get("ok", True) if isinstance(r, dict) else r.success for r in all_results)
        return SkillResult(skill_name=manifest.name, success=success, step_results=all_results, context=ctx)

    @staticmethod
    def _render_template(template: str, ctx: Dict[str, Any]) -> str:
        def _replace(match):
            key = match.group(1)
            val = ctx.get(key, match.group(0))
            if isinstance(val, str):
                return val
            return json.dumps(val)
        return re.sub(r"\{(\w+)\}", _replace, template)


__all__ = ["SkillExecutor", "SkillResult", "SkillResolver"]
