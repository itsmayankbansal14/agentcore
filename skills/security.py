"""Skill security — capability validation and trust tiers.

Adapted from OpenJarvis src/openjarvis/skills/security.py
Apache-2.0
"""

from __future__ import annotations

from enum import Enum
from typing import List, Set

from skills.types import SkillManifest

DANGEROUS_CAPABILITIES: frozenset[str] = frozenset(
    {"shell:execute", "network:listen", "filesystem:write"}
)


class TrustTier(str, Enum):
    BUNDLED = "bundled"
    INDEXED = "indexed"
    WORKSPACE = "workspace"
    UNREVIEWED = "unreviewed"


def classify_trust_tier(
    *,
    is_bundled: bool = False,
    is_workspace: bool = False,
    has_signature: bool = False,
    in_index: bool = False,
) -> TrustTier:
    if is_bundled:
        return TrustTier.BUNDLED
    if is_workspace:
        return TrustTier.WORKSPACE
    if has_signature and in_index:
        return TrustTier.INDEXED
    return TrustTier.UNREVIEWED


def validate_capabilities(manifest: SkillManifest, allowed: Set[str]) -> List[str]:
    return [cap for cap in manifest.required_capabilities if cap not in allowed]


def has_dangerous_capabilities(manifest: SkillManifest) -> List[str]:
    return [cap for cap in manifest.required_capabilities if cap in DANGEROUS_CAPABILITIES]


__all__ = [
    "DANGEROUS_CAPABILITIES",
    "TrustTier",
    "classify_trust_tier",
    "validate_capabilities",
    "has_dangerous_capabilities",
]
