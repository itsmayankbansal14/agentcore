"""AgentCore — llm/providers/openai_compat.py
OpenAI provider + any OpenAI-compatible vendor (DeepSeek, Groq, OpenRouter…).
Also provides embeddings.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from core.contracts import (LLMMessage, LLMResponse, LLMUsage, Role, ToolCall, ToolSpec)
from llm.providers.base import BaseProvider, ProviderUnavailableError

_ROLE_MAP = {
    Role.SYSTEM: "system", Role.USER: "user",
    Role.ASSISTANT: "assistant", Role.TOOL: "tool",
}


class OpenAICompatProvider(BaseProvider):
    name = "openai"

    def __init__(self, model: str, api_key: str = "", base_url: str = "",
                 default_headers: dict | None = None, **kw: Any) -> None:
        super().__init__(model=model, api_key=api_key, base_url=base_url,
                         default_headers=default_headers, **kw)
        self._client = None

    def _client_or_none(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailableError(f"openai SDK missing: {e}")
        kwargs: dict[str, Any] = {"api_key": self.api_key or "not-set"}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        if self.default_headers:
            kwargs["default_headers"] = self.default_headers
        self._client = OpenAI(**kwargs)
        return self._client

    def _to_native(self, messages: list[LLMMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            d: dict[str, Any] = {"role": _ROLE_MAP[m.role]}
            if m.content is not None:
                d["content"] = m.content   # str OR list of multimodal parts
            if m.tool_calls:
                d["tool_calls"] = [{
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.name, "arguments": _json(tc.arguments)},
                } for tc in m.tool_calls]
            if m.tool_call_id:
                d["tool_call_id"] = m.tool_call_id
            out.append(d)
        return out

    def _tools_native(self, tools: list[ToolSpec] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [{
            "type": "function",
            "function": {"name": t.name, "description": t.description,
                         "parameters": t.parameters},
        } for t in tools]

    async def chat(self, messages, tools=None, **kw) -> LLMResponse:
        client = self._client_or_none()
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=self._to_native(messages),
                tools=self._tools_native(tools),
                temperature=kw.get("temperature", self.temperature),
                max_tokens=kw.get("max_tokens", self.max_tokens),
            )
        except Exception as e:  # noqa: BLE001
            raise self.classify_error(e)
        msg = resp.choices[0].message
        tool_calls = []
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                import json as _j
                try:
                    args = _j.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        usage = LLMUsage(
            prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
            total_tokens=resp.usage.total_tokens if resp.usage else 0,
        )
        return LLMResponse(content=msg.content, tool_calls=tool_calls, usage=usage,
                           provider=self.name, model=self.model,
                           finish_reason=resp.choices[0].finish_reason or "", raw=resp)

    async def stream(self, messages, **kw) -> AsyncIterator[str]:
        client = self._client_or_none()
        stream = client.chat.completions.create(
            model=self.model, messages=self._to_native(messages), stream=True,
            temperature=kw.get("temperature", self.temperature),
            max_tokens=kw.get("max_tokens", self.max_tokens))
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def embed(self, text: str) -> list[float]:
        client = self._client_or_none()
        resp = client.embeddings.create(model="text-embedding-3-small", input=text)
        return resp.data[0].embedding


def _json(obj: dict) -> str:
    import json
    return json.dumps(obj)


class DeepSeekProvider(OpenAICompatProvider):
    name = "deepseek"


class OpenRouterProvider(OpenAICompatProvider):
    """OpenAI-compatible facade for OpenRouter (base_url + headers from config)."""
    name = "openrouter"
