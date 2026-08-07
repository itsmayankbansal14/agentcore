"""AgentCore — reasoning/local.py + human.py
LocalReasoner: deterministic heuristic decomposition (no LLM, no network).
HumanReasoner: asks the user to approve/author subtasks (CLI or UI callback).
"""
from __future__ import annotations

import re
from typing import Callable

from reasoning.base import Decomposition, Reasoner

_SPLIT = re.compile(r"\s+(?:then|next|and then|after that|finally)\s+", re.I)


class LocalReasoner(Reasoner):
    name = "local"

    async def decompose(self, goal: str) -> Decomposition | None:
        parts = [p.strip() for p in _SPLIT.split(goal) if p.strip()]
        if len(parts) >= 2:
            return Decomposition(steps=parts, engine="local", confidence=0.6)
        return None  # single-step goals are handled by the planner directly

    async def reflect(self, context: str, prompt: str) -> str | None:
        return None  # no reasoning without a model


class HumanReasoner(Reasoner):
    """Interactive decomposition. `ask` is pluggable (CLI input, UI prompt…)."""

    name = "human"

    def __init__(self, ask: Callable[[str], str] | None = None) -> None:
        self._ask = ask or default_ask

    async def decompose(self, goal: str) -> Decomposition | None:
        answer = self._ask(
            f"🧠 I need you to break this goal into steps:\n  “{goal}”\n"
            "Give me a comma-separated list of 2-6 steps (or 'auto' for heuristic): "
        ).strip()
        if not answer or answer.lower() in ("auto", "automatic"):
            return None
        steps = [s.strip() for s in re.split(r"[,;]", answer) if s.strip()]
        if len(steps) >= 2:
            return Decomposition(steps=steps[:6], engine="human")
        return None

    async def reflect(self, context: str, prompt: str) -> str | None:
        return self._ask(f"{prompt}\nContext: {context[:400]}\nAnswer: ")


def default_ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""
