"""AgentCore — reasoning/base.py
Reasoner interface. Decouples the Planner (and anything that "thinks") from
the concrete reasoning implementation. The LLMManager stays the provider
facade; Reasoner is the planning-specific seam.

  Planner → Reasoner → {LLMReasoner (openai/gemini/claude/… via LLMManager),
                        LocalReasoner (heuristic), HumanReasoner (ask the user)}

This lets planning be performed by a different engine than the chat loop
(e.g. a local planner, or a human approving every plan) without touching
the Planner.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Decomposition:
    """Result of decomposing a goal into ordered subtasks."""
    steps: list[str]
    engine: str          # which reasoner produced it (for audit)
    confidence: float = 1.0


class Reasoner(ABC):
    name: str = "base"

    @abstractmethod
    async def decompose(self, goal: str) -> Decomposition | None:
        """Break a goal into 2-6 sequential subtasks. None = cannot (caller falls back)."""
        ...

    @abstractmethod
    async def reflect(self, context: str, prompt: str) -> str | None:
        """General reasoning call (summarization, verification, reflection)."""
        ...
