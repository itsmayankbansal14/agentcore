"""Skill loader — load and verify skill manifests.

Adapted from OpenJarvis src/openjarvis/skills/loader.py
Apache-2.0
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from skills.types import SkillManifest, SkillStep
from skills.parser import SkillParser

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

import logging

LOGGER = logging.getLogger(__name__)


def _read_source_metadata(path: Path) -> dict:
    source_path = path / ".source"
    if not source_path.exists():
        return {}
    try:
        with open(source_path, "rb") as fh:
            return tomllib.load(fh)
    except Exception as exc:
        LOGGER.warning("Malformed .source sidecar at %s: %s", source_path, exc)
        return {}


def load_skill_markdown(md_path: Path) -> SkillManifest:
    raw = md_path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(raw)
    parser = SkillParser()
    manifest = parser.parse_frontmatter(frontmatter, markdown_content=body)
    return manifest


def load_skill_directory(path: Path) -> SkillManifest:
    path = Path(path)
    toml_path = path / "skill.toml"
    md_path = path / "SKILL.md"
    if not md_path.exists():
        md_path = path / "skill.md"

    if toml_path.exists() and md_path.exists():
        # Load both and merge markdown content
        manifest = load_skill(toml_path)
        md_manifest = load_skill_markdown(md_path)
        manifest.markdown_content = md_manifest.markdown_content
        return manifest
    elif md_path.exists():
        return load_skill_markdown(md_path)
    elif toml_path.exists():
        return load_skill(toml_path)
    else:
        raise FileNotFoundError(f"No skill definition found in {path}")


def load_skill(path: str | Path) -> SkillManifest:
    path = Path(path)
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    skill_data = data.get("skill", {})
    steps = []
    for step_data in skill_data.get("steps", []):
        steps.append(
            SkillStep(
                tool_name=step_data.get("tool_name", ""),
                skill_name=step_data.get("skill_name", ""),
                arguments_template=step_data.get("arguments_template", "{}"),
                output_key=step_data.get("output_key", ""),
            )
        )
    manifest = SkillManifest(
        name=skill_data.get("name", path.stem),
        version=skill_data.get("version", "0.1.0"),
        description=skill_data.get("description", ""),
        author=skill_data.get("author", ""),
        steps=steps,
        required_capabilities=skill_data.get("required_capabilities", []),
        signature=skill_data.get("signature", ""),
        metadata=skill_data.get("metadata", {}),
        tags=skill_data.get("tags", []),
        depends=skill_data.get("depends", []),
        user_invocable=skill_data.get("user_invocable", True),
        disable_model_invocation=skill_data.get("disable_model_invocation", False),
    )
    return manifest


def discover_skills(directory: str | Path) -> list[SkillManifest]:
    directory = Path(directory).expanduser()
    if not directory.exists():
        return []
    manifests = []
    for toml_file in sorted(directory.glob("*.toml")):
        try:
            manifests.append(load_skill(toml_file))
        except Exception as exc:
            LOGGER.warning("Failed to load skill from %s: %s", toml_file, exc)
    for child in sorted(directory.iterdir()):
        if not child.is_dir():
            continue
        if (child / "skill.toml").exists() or (child / "SKILL.md").exists():
            try:
                manifests.append(load_skill_directory(child))
            except Exception as exc:
                LOGGER.warning("Failed to load skill from %s: %s", child, exc)
    return manifests


def _split_frontmatter(raw: str):
    if not raw.startswith("---"):
        return {}, raw
    rest = raw[3:].lstrip("\n")
    end = rest.find("\n---")
    if end == -1:
        return {}, raw
    fm_text = rest[:end]
    body = rest[end + 4 :].lstrip("\n")
    try:
        fm = yaml.safe_load(fm_text) or {}
        if not isinstance(fm, dict):
            fm = {}
    except Exception:
        fm = {}
    return fm, body


__all__ = ["load_skill", "load_skill_markdown", "load_skill_directory", "discover_skills"]
