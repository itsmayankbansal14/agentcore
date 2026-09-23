"""Dependency graph utilities.

Adapted from OpenJarvis src/openjarvis/skills/dependency.py
Apache-2.0
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Set

from skills.types import SkillManifest


class DependencyCycleError(Exception):
    def __init__(self, message: str, skills: Set[str] | None = None):
        super().__init__(message)
        self.skills = skills or set()


class DepthExceededError(Exception):
    pass


def build_dependency_graph(skills: Dict[str, SkillManifest]) -> Dict[str, Set[str]]:
    graph = {name: set() for name in skills}
    for name, manifest in skills.items():
        for dep in manifest.depends:
            if dep in skills:
                graph[name].add(dep)
        for step in manifest.steps:
            if step.skill_name and step.skill_name in skills:
                graph[name].add(step.skill_name)
    return graph


def validate_dependencies(skills: Dict[str, SkillManifest], *, max_depth: int = 5) -> List[str]:
    graph = build_dependency_graph(skills)
    in_degree = {name: len(deps) for name, deps in graph.items()}
    reverse = {name: set() for name in graph}
    for name, deps in graph.items():
        for dep in deps:
            reverse[dep].add(name)
    queue = deque([n for n, d in in_degree.items() if d == 0])
    order = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for dependent in reverse[node]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
    if len(order) != len(graph):
        cyclic = set(graph) - set(order)
        raise DependencyCycleError(f"Cycle detected: {cyclic}", skills=cyclic)
    depth_cache: Dict[str, int] = {}
    def _depth(name: str, visiting: Set[str]) -> int:
        if name in depth_cache:
            return depth_cache[name]
        deps = graph.get(name, set())
        if not deps:
            depth_cache[name] = 1
            return 1
        visiting.add(name)
        max_child = max(_depth(d, visiting) for d in deps)
        visiting.discard(name)
        result = max_child + 1
        depth_cache[name] = result
        return result
    for name in graph:
        d = _depth(name, set())
        if d > max_depth:
            raise DepthExceededError(f"Skill '{name}' depth {d} exceeds max_depth={max_depth}")
    return order


def compute_capability_union(skill_name: str, skills: Dict[str, SkillManifest]) -> List[str]:
    if skill_name not in skills:
        return []
    graph = build_dependency_graph(skills)
    seen_skills: Set[str] = set()
    seen_caps: Set[str] = set()
    caps_ordered: List[str] = []
    def _dfs(name: str):
        if name in seen_skills:
            return
        seen_skills.add(name)
        manifest = skills.get(name)
        if manifest is None:
            return
        for cap in manifest.required_capabilities:
            if cap not in seen_caps:
                seen_caps.add(cap)
                caps_ordered.append(cap)
        for dep in graph.get(name, set()):
            _dfs(dep)
    _dfs(skill_name)
    return caps_ordered


__all__ = ["DependencyCycleError", "DepthExceededError", "build_dependency_graph", "validate_dependencies", "compute_capability_union"]
