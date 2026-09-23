"""SkillParser — strict spec validation + tolerant field mapping.

Adapted from OpenJarvis src/openjarvis/skills/parser.py
Apache-2.0
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

from skills.types import SkillManifest

LOGGER = logging.getLogger(__name__)

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_COMPATIBILITY_LENGTH = 500

SPEC_FIELDS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)

FIELD_MAPPING: Dict[str, tuple[str, str]] = {
    "version": ("field", "version"),
    "author": ("field", "author"),
    "tags": ("field", "tags"),
    "depends": ("field", "depends"),
    "required_capabilities": ("field", "required_capabilities"),
    "user_invocable": ("field", "user_invocable"),
    "disable_model_invocation": ("field", "disable_model_invocation"),
    "platforms": ("openjarvis_meta", "platforms"),
    "prerequisites": ("openjarvis_meta", "prerequisites"),
}

_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?!-))*[a-z0-9]$|^[a-z0-9]$")


class SkillParseError(ValueError):
    """Raised when a skill frontmatter cannot be parsed."""


class SkillParser:
    """Parse SKILL.md frontmatter into a SkillManifest."""

    def parse_frontmatter(
        self,
        frontmatter: Dict[str, Any],
        *,
        markdown_content: str = "",
    ) -> SkillManifest:
        self._validate_strict(frontmatter)
        return self._build_manifest(frontmatter, markdown_content)

    def _validate_strict(self, frontmatter: Dict[str, Any]) -> None:
        if "name" not in frontmatter:
            raise SkillParseError("Missing required field in frontmatter: name")
        if "description" not in frontmatter:
            raise SkillParseError("Missing required field in frontmatter: description")

        name = frontmatter["name"]
        description = frontmatter["description"]

        if not isinstance(name, str):
            raise SkillParseError(f"Field 'name' must be a string, got {type(name)}")
        if not isinstance(description, str):
            raise SkillParseError(
                f"Field 'description' must be a string, got {type(description)}"
            )

        if len(name) == 0 or len(name) > MAX_NAME_LENGTH:
            raise SkillParseError(
                f"Field 'name' must be 1-{MAX_NAME_LENGTH} chars, got {len(name)}"
            )
        if len(description) == 0 or len(description) > MAX_DESCRIPTION_LENGTH:
            raise SkillParseError(
                f"Field 'description' must be 1-{MAX_DESCRIPTION_LENGTH} chars, "
                f"got {len(description)}"
            )

        self._validate_name(name)

        compat = frontmatter.get("compatibility")
        if compat is not None:
            if not isinstance(compat, str):
                raise SkillParseError("Field 'compatibility' must be a string")
            if len(compat) > MAX_COMPATIBILITY_LENGTH:
                raise SkillParseError(
                    f"Field 'compatibility' exceeds {MAX_COMPATIBILITY_LENGTH} chars"
                )

    def _validate_name(self, name: str) -> None:
        if name != name.lower():
            raise SkillParseError(f"Skill name '{name}' must be lowercase")
        if name.startswith("-") or name.endswith("-"):
            raise SkillParseError(
                f"Skill name '{name}' must not start or end with a hyphen"
            )
        if "--" in name:
            raise SkillParseError(
                f"Skill name '{name}' must not contain consecutive hyphens"
            )
        for ch in name:
            if not (ch.isalnum() or ch == "-"):
                raise SkillParseError(
                    f"Skill name '{name}' contains invalid character '{ch}'; "
                    f"only lowercase alphanumeric and hyphens are allowed"
                )

    def _build_manifest(
        self,
        frontmatter: Dict[str, Any],
        markdown_content: str,
    ) -> SkillManifest:
        manifest = SkillManifest(
            name=frontmatter["name"],
            description=frontmatter["description"],
            markdown_content=markdown_content,
        )

        raw_metadata = frontmatter.get("metadata") or {}
        if not isinstance(raw_metadata, dict):
            raw_metadata = {}
        oj_meta = dict(raw_metadata.get("openjarvis") or {})

        unmapped: Dict[str, Any] = {}
        for key, value in frontmatter.items():
            if key in SPEC_FIELDS:
                continue
            if key in FIELD_MAPPING:
                target, attr = FIELD_MAPPING[key]
                if target == "field":
                    setattr(manifest, attr, value)
                else:
                    oj_meta[attr] = value
            else:
                unmapped[key] = value
                LOGGER.warning(
                    "Unmapped frontmatter field '%s' in skill '%s' "
                    "(value preserved in metadata.openjarvis.original_frontmatter)",
                    key,
                    manifest.name,
                )

        for key in (
            "version",
            "author",
            "tags",
            "depends",
            "required_capabilities",
            "user_invocable",
            "disable_model_invocation",
        ):
            if key in oj_meta:
                setattr(manifest, key, oj_meta[key])

        if unmapped:
            oj_meta["original_frontmatter"] = unmapped

        if oj_meta:
            new_metadata = dict(raw_metadata)
            new_metadata["openjarvis"] = oj_meta
            manifest.metadata = new_metadata
        else:
            manifest.metadata = raw_metadata

        return manifest


__all__ = ["SkillParseError", "SkillParser", "SPEC_FIELDS", "FIELD_MAPPING"]
