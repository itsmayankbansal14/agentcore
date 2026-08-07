"""AgentCore — memory/extractor.py
Lightweight rule-based fact extraction from user messages → LTM candidates.
MVP: regex patterns (works offline). Later: LLM-based extraction async job.

Returns list of (kind, key, content, confidence).
"""
from __future__ import annotations

import re

_CAPTURE = r"([^.,!]+)"  # capture up to punctuation/end — avoids non-greedy "J" bugs

_PATTERNS = [
    # "my name is X"
    (r"\bmy name is ([A-Z][a-zA-Z]+)", "identity", "user.name", 0.95),
    (r"\bi am ([A-Z][a-zA-Z]+)", "identity", "user.name", 0.85),
    # location
    (rf"\bi (?:live|stay|reside) in {_CAPTURE}", "fact", "user.location", 0.9),
    # preferences
    (rf"\bi (?:prefer|like|love|enjoy) {_CAPTURE}", "preference", "user.like", 0.8),
    (rf"\bi (?:don'?t|do not) (?:like|enjoy) {_CAPTURE}", "preference", "user.dislike", 0.8),
    # explicit remember
    (rf"remember (?:that )?(?:i |my )?{_CAPTURE}", "fact", "explicit.remember", 0.95),
    (rf"from now on,? (?:call me|refer to me as) {_CAPTURE}", "identity", "user.alias", 0.9),
    # goals / study
    (rf"\bi'?m (?:studying|learning) {_CAPTURE}", "project", "user.studying", 0.9),
    (rf"\bi (?:work|code) (?:on|with) {_CAPTURE}", "project", "user.project", 0.85),
    # daily routines
    (r"\bi (?:wake up|get up) (?:at )?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", "preference", "user.wake_time", 0.8),
    (rf"\bmy (?:favorite|favourite) {_CAPTURE} is {_CAPTURE}", "preference", "user.fav", 0.85),
]


def extract_facts(message: str) -> list[tuple[str, str, str, float]]:
    """Return [(kind, key, content, confidence), ...] deduped by key."""
    found: dict[str, tuple[str, str, str, float]] = {}
    for pattern, kind, key_base, conf in _PATTERNS:
        for m in re.finditer(pattern, message, re.I):
            value = m.group(1).strip().strip(".")
            if not value or len(value) > 60:
                continue
            key = key_base
            # uniqueness for generic keys: incorporate value hash to avoid collisions
            if key in ("user.like", "user.dislike", "user.fav", "explicit.remember",
                       "user.studying", "user.project"):
                key = f"{key}.{abs(hash(value.lower())) % 100000}"
            found[key] = (kind, key, value, conf)
    return list(found.values())
