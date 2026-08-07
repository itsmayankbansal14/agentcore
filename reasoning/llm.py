"""AgentCore — reasoning/llm.py
LLMReasoner: delegates to the LLMManager (which routes OpenAI/Gemini/Claude/
DeepSeek/Ollama/OpenRouter internally). Provider-specific reasoners are just
LLMReasoner bound to a provider name — no per-vendor code needed here.
"""
from __future__ import annotations

import json
import logging

import structlog

from core.contracts import LLMMessage, Role
from reasoning.base import Decomposition, Reasoner

log = structlog.get_logger("agentcore.reasoning.llm")

_DECOMPOSE_PROMPT = (
    "Break this user goal into 2-6 sequential subtasks. "
    'Reply ONLY with a JSON array of short strings, e.g. '
    '["install deps", "scaffold app", "write tests"].\nGoal: '
)


class LLMReasoner(Reasoner):
    name = "llm"

    def __init__(self, llm_manager, provider: str | None = None) -> None:
        self.llm = llm_manager
        self._provider = provider  # None = follow LLMManager rotation

    async def decompose(self, goal: str) -> Decomposition | None:
        prompt = _DECOMPOSE_PROMPT + goal
        try:
            resp = await self.llm.chat([LLMMessage(role=Role.USER, content=prompt)])
        except Exception:  # noqa: BLE001
            log.debug("reasoner decompose: llm failed", goal=goal[:60])
            return None
        text = (resp.content or "").strip()
        if not text.startswith("["):
            log.debug("reasoner decompose: no JSON array", snippet=text[:60])
            return None
        try:
            text = text[text.find("["): text.rfind("]") + 1]
            steps = json.loads(text)
        except Exception:  # noqa: BLE001
            return None
        if isinstance(steps, list) and steps and all(isinstance(s, str) for s in steps):
            return Decomposition(steps=[s.strip() for s in steps], engine="llm")
        return None

    async def reflect(self, context: str, prompt: str) -> str | None:
        try:
            resp = await self.llm.chat([
                LLMMessage(role=Role.SYSTEM, content=prompt),
                LLMMessage(role=Role.USER, content=context[:4000]),
            ])
            return (resp.content or "").strip() or None
        except Exception:  # noqa: BLE001
            return None
