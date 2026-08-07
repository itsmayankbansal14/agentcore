"""AgentCore — llm/providers/mock.py
Scriptable in-memory provider. No network. Used for tests, offline mode,
and exercising the router/loop without an API key.

Script directives in responses:
  [TOOL name json]     -> request a tool call
  [FAIL_RATE_ONCE]     -> raise RateLimitError on the next call (failover tests)
  [FAIL_AUTH]          -> raise AuthError
  [FAIL_OVERFLOW]      -> raise ContextOverflowError
  [ECHO]               -> echo the last user message back
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from core.contracts import LLMMessage, LLMResponse, ToolCall, LLMUsage, Role
from llm.providers.base import BaseProvider, RateLimitError, AuthError, ContextOverflowError


class MockProvider(BaseProvider):
    name = "mock"

    def __init__(self, model: str = "mock-1", api_key: str = "mock-key",
                 **kw: Any) -> None:
        super().__init__(model=model, api_key=api_key, **kw)
        self.call_count = 0
        self.fail_rate_once = False
        self.fail_auth = False
        self.fail_overflow = False
        self.script: list[str] = []   # queue of response lines

    def enqueue(self, *lines: str) -> None:
        self.script.extend(lines)

    async def chat(self, messages: list[LLMMessage], tools=None, **kw) -> LLMResponse:
        self.call_count += 1
        if self.fail_rate_once:
            self.fail_rate_once = False
            raise RateLimitError("mock rate limited (429)")
        if self.fail_auth:
            self.fail_auth = False
            raise AuthError("mock invalid api key (401)")
        if self.fail_overflow:
            self.fail_overflow = False
            raise ContextOverflowError("mock context length exceeded")

        # reply: consume script or default to echoing
        line = self.script.pop(0) if self.script else "[ECHO]"
        if line == "[ECHO]":
            last_user = next((m.content for m in reversed(messages)
                              if m.role == Role.USER and m.content), "hi")
            content = f"[mock:{self.model}] you said: {last_user}"
            return LLMResponse(content=content, provider=self.name, model=self.model,
                               usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))
        if line.startswith("[TOOL "):
            # format: [TOOL name {"arg":"val"}]
            rest = line[len("[TOOL "):].rstrip("]").strip()
            name, _, args = rest.partition(" ")
            tc = ToolCall(id=f"call_{self.call_count}", name=name,
                          arguments=json.loads(args) if args.strip() else {})
            return LLMResponse(content=None, tool_calls=[tc], provider=self.name,
                               model=self.model, finish_reason="tool_calls")
        content = line
        return LLMResponse(content=content, provider=self.name, model=self.model,
                           usage=LLMUsage(prompt_tokens=len(messages), completion_tokens=len(content) // 4,
                                          total_tokens=len(messages) + len(content) // 4))

    async def stream(self, messages: list[LLMMessage], **kw) -> AsyncIterator[str]:
        resp = await self.chat(messages, **kw)
        for word in (resp.content or "").split(" "):
            yield word + " "

    async def embed(self, text: str) -> list[float]:
        # deterministic pseudo-embedding for tests
        return [float(ord(c) % 10) / 10.0 for c in text[:16].ljust(16, " ")]

    def count_tokens(self, text: str) -> int:
        return len(text.split())
