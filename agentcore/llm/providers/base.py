"""AgentCore — llm/providers/base.py
Provider abstract base. Every vendor implements chat/stream/embed/count_tokens
and translates the normalized messages to/from its own format. This is the
ONLY file per vendor anyone ever edits.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from core.contracts import LLMMessage, LLMResponse, ToolSpec


class ProviderError(Exception):
    """Base provider error."""


class RateLimitError(ProviderError):
    """Rate limited / quota exceeded / 429."""


class AuthError(ProviderError):
    """Bad key / 401 / 403."""


class ContextOverflowError(ProviderError):
    """Prompt too long for this model's context window."""


class ProviderUnavailableError(ProviderError):
    """Network, 5xx, SDK missing, service down."""


class BaseProvider(ABC):
    name: str = "base"

    def __init__(self, model: str, api_key: str = "", base_url: str = "",
                 default_headers: dict | None = None,
                 temperature: float = 0.7, max_tokens: int = 700) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.default_headers = default_headers or {}
        self.temperature = temperature
        self.max_tokens = max_tokens

    # -- to be implemented per provider ------------------------------------
    @abstractmethod
    async def chat(self, messages: list[LLMMessage], tools: list[ToolSpec] | None = None,
                   **kw: Any) -> LLMResponse: ...

    @abstractmethod
    async def stream(self, messages: list[LLMMessage], **kw: Any) -> AsyncIterator[str]: ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...

    # -- shared helpers ------------------------------------------------------
    def count_tokens(self, text: str) -> int:
        """Rough token estimate (chars/4). Providers may override with real tokenizers."""
        return max(1, len(text) // 4)

    def is_available(self) -> bool:
        return bool(self.api_key or self.name == "mock")

    def classify_error(self, exc: Exception) -> ProviderError:
        msg = str(exc).lower()
        if any(s in msg for s in ("429", "rate limit", "quota", "insufficient_quota",
                                  "too many requests", "capacity")):
            return RateLimitError(str(exc))
        if any(s in msg for s in ("401", "403", "authentication", "api key", "invalid api",
                                  "permission denied", "unauthorized")):
            return AuthError(str(exc))
        if any(s in msg for s in ("context length", "too many tokens", "maximum context",
                                  "token limit", "prompt is too long")):
            return ContextOverflowError(str(exc))
        if any(s in msg for s in ("timeout", "connection", "5", "server error", "overloaded",
                                  "sdk", "no module", "failed to import")):
            return ProviderUnavailableError(str(exc))
        return ProviderError(str(exc))
