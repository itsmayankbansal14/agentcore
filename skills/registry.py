"""Skill registry wrapper around AgentCore ToolRegistry.

Adapted from OpenJarvis SkillManager concepts
Apache-2.0
"""

from __future__ import annotations

from pathlib import Path
from typing import List
from skills.catalog import SkillCatalog
from skills.types import SkillManifest


class SkillRegistry:
    def __init__(self, roots: List[Path] | None = None):
        self._catalog = SkillCatalog(roots)

    def discover(self, paths):
        self._catalog.discover(paths)

    def get(self, name: str) -> SkillManifest | None:
        return self._catalog.get(name)

    def search(self, query: str):
        return self._catalog.search(query)

    def list(self):
        return self._catalog.list_names()
