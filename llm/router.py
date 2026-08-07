"""AgentCore — llm/router.py
Provider selection, API-key rotation, and failover.

Continuity across switches is free: the message list lives in the session
(DB), never inside a provider. The router simply replays the same normalized
messages to the next healthy provider/key. On context-overflow it asks the
memory layer for a summary and retries with the trimmed context.
"""
from __future__ import annotations

import structlog
import time
from dataclasses import dataclass, field
from typing import Any

from core.bus import EventBus
from core.bus import EventBus
from core.contracts import Event, EventType, LLMMessage, LLMResponse, ToolSpec
from llm.providers import (AuthError, BaseProvider, ContextOverflowError,
                           ProviderError, ProviderUnavailableError, RateLimitError)

log = structlog.get_logger("agentcore.llm.router")


@dataclass
class KeyRuntime:
    provider: str
    key: str
    model: str
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    last_error: str = ""


@dataclass
class RouterState:
    keys: list[KeyRuntime] = field(default_factory=list)

    def healthy_keys(self, now: float | None = None) -> list[KeyRuntime]:
        now = now or time.time()
        return [k for k in self.keys if k.cooldown_until <= now]


class LLMRouter:
    """Tries provider→key in priority order; rotates on failure; persists
    health state via the caller-provided state hook (SQLite in prod)."""

    def __init__(self, keys: list[KeyRuntime], bus: EventBus | None = None,
                 state_store: Any = None, cooldown_seconds: int = 300) -> None:
        self.keys = keys
        self.bus = bus
        self.state_store = state_store   # optional LLMProviderState repo
        self.cooldown_seconds = cooldown_seconds

    # -- state persistence -------------------------------------------------
    def healthy_keys(self) -> list[KeyRuntime]:
        now = time.time()
        return [k for k in self.keys if k.cooldown_until <= now]

    def _persist_health(self, key: KeyRuntime) -> None:
        if self.state_store:
            try:
                self.state_store.update_provider(key.provider, key)
            except Exception:  # noqa: BLE001
                log.exception("state_store update failed")

    def _mark_failure(self, key: KeyRuntime, err: ProviderError) -> None:
        key.consecutive_failures += 1
        key.last_error = str(err)
        # rate limits & auth get a cooldown; transient keep trying next provider
        if isinstance(err, (RateLimitError, AuthError)):
            key.cooldown_until = time.time() + self.cooldown_seconds
        self._persist_health(key)
        if self.bus:
            self.bus.emit(EventType.PROVIDER_FAILED,
                          {"provider": key.provider, "error": str(err)})

    def _mark_success(self, key: KeyRuntime) -> None:
        key.consecutive_failures = 0
        key.cooldown_until = 0.0
        self._persist_health(key)

    # -- main call ---------------------------------------------------------
    async def chat(self, provider_factory, messages: list[LLMMessage],
                   tools: list[ToolSpec] | None = None, session_id: str | None = None,
                   on_overflow: Any = None, **kw: Any) -> LLMResponse:
        """
        provider_factory(provider_name, key, model) -> BaseProvider
        on_overflow(session_id, messages) -> list[LLMMessage]  (returns trimmed msgs)
        """
        errors: list[str] = []
        for key in self.healthy_keys():
            try:
                provider = provider_factory(key.provider, key.key, key.model)
                resp = await provider.chat(messages, tools=tools, **kw)
                self._mark_success(key)
                if self.bus:
                    self.bus.emit(EventType.PROVIDER_SWITCHED,
                                  {"provider": key.provider, "model": key.model})
                return resp
            except ContextOverflowError as e:
                self._mark_failure(key, e)
                if on_overflow:
                    trimmed = on_overflow(session_id, messages)
                    if trimmed is not None:
                        log.warning("context overflow — trimmed history, retrying", provider=key.provider)
                        try:
                            provider = provider_factory(key.provider, key.key, key.model)
                            resp = await provider.chat(trimmed, tools=tools, **kw)
                            self._mark_success(key)
                            return resp
                        except ProviderError as e2:
                            errors.append(f"{key.provider}: {e2}")
                            continue
                errors.append(f"{key.provider}: {e}")
            except (RateLimitError, AuthError, ProviderUnavailableError) as e:
                self._mark_failure(key, e)
                errors.append(f"{key.provider}: {e}")
            except ProviderError as e:
                errors.append(f"{key.provider}: {e}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{key.provider}: unexpected {e}")
        raise ProviderUnavailableError("all providers failed: " + " | ".join(errors))
