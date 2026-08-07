"""AgentCore — llm/manager.py
The ONLY public face of the LLM layer. The rest of the app (agents, planner,
memory summarizer) calls LLMManager.chat/stream/embed and never touches a
provider SDK or a key.
"""
from __future__ import annotations

import structlog
from typing import Any, AsyncIterator, Callable

from config.manager import ConfigManager
from core.bus import EventBus
from core.contracts import LLMMessage, LLMResponse, ToolSpec
from llm.providers import PROVIDER_CLASSES, BaseProvider
from llm.router import KeyRuntime, LLMRouter

log = structlog.get_logger("agentcore.llm")


class LLMManager:
    def __init__(self, config: ConfigManager, bus: EventBus | None = None,
                 state_store: Any = None) -> None:
        self.config = config
        self.bus = bus
        self.state_store = state_store
        self.router = self._build_router()

    # -- construction ------------------------------------------------------
    def _build_router(self) -> LLMRouter:
        priority = self.config.get_list("llm.provider_priority", ["mock"])
        defaults = self.config.get("llm.default_model", {}) or {}
        keys: list[KeyRuntime] = []
        for prov in priority:
            model = defaults.get(prov, "default")
            prov_keys = self.config.api_keys(prov)
            if prov == "mock" or not prov_keys:
                # mock + providers without configured keys still register
                # (router skips them because provider.is_available() is False)
                if prov == "mock":
                    keys.append(KeyRuntime(provider="mock", key="mock-key", model=model))
                continue
            for k in prov_keys:
                keys.append(KeyRuntime(provider=prov, key=k, model=model))
        # if nothing configured, keep a mock so offline mode works
        if not keys:
            keys.append(KeyRuntime(provider="mock", key="mock-key", model="mock-1"))
        return LLMRouter(keys, bus=self.bus, state_store=self.state_store,
                         cooldown_seconds=self.config.get_int("llm.cooldown_seconds", 300))

    def _factory(self, provider_name: str, key: str, model: str) -> BaseProvider:
        cls = PROVIDER_CLASSES.get(provider_name)
        if cls is None:
            raise ValueError(f"unknown provider: {provider_name}")
        base_url = self.config.get_str(f"llm.base_url.{provider_name}", "")
        headers = self.config.get(f"llm.headers.{provider_name}", {}) or {}
        return cls(model=model, api_key=key, base_url=base_url,
                   default_headers=headers or None,
                   temperature=self.config.get_float("llm.temperature", 0.7),
                   max_tokens=self.config.get_int("llm.max_tokens", 700))

    # -- public API --------------------------------------------------------
    async def chat(self, messages: list[LLMMessage], tools: list[ToolSpec] | None = None,
                   session_id: str | None = None,
                   on_overflow: Callable | None = None, **kw: Any) -> LLMResponse:
        return await self.router.chat(self._factory, messages, tools=tools,
                                      session_id=session_id, on_overflow=on_overflow, **kw)

    async def stream(self, messages: list[LLMMessage], **kw: Any) -> AsyncIterator[str]:
        """Stream from the first healthy provider (simpler than rotation for MVP)."""
        resp = await self.chat(messages, **kw)
        for word in (resp.content or "").split(" "):
            yield word + " "

    async def embed(self, text: str) -> list[float]:
        factory = self._factory
        key = self.router.healthy_keys()[0]
        provider = factory(key.provider, key.key, key.model)
        return await provider.embed(text)

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)
