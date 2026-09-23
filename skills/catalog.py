"""Skill catalog and discovery.

Adapted from OpenJarvis src/openjarvis/skills/index.py and manager discovery
Apache-2.0
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from skills.types import SkillManifest
from skills.loader import discover_skills


class SkillCatalog:
    def __init__(self, roots: List[Path] | None = None):
        self._roots = roots or []
        self._skills: Dict[str, SkillManifest] = {}
        self.discover()

    def discover(self, extra_paths: List[Path] | None = None):
        paths = list(self._roots)
        if extra_paths:
            paths.extend(extra_paths)
        for directory in paths:
            for manifest in discover_skills(directory):
                if manifest.name not in self._skills:
                    self._skills[manifest.name] = manifest

    def get(self, name: str) -> Optional[SkillManifest]:
        return self._skills.get(name)

    def list_names(self) -> List[str]:
        return list(self._skills.keys())

    def search(self, query: str) -> List[SkillManifest]:
        q = query.lower()
        results = []
        for m in self._skills.values():
            if q in m.name.lower() or q in m.description.lower() or any(q in t.lower() for t in m.tags):
                results.append(m)
        return results

    def all(self) -> Dict[str, SkillManifest]:
        return dict(self._skills)


__all__ = ["SkillCatalog"]
