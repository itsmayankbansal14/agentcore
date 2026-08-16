"""AgentCore — llm/providers/gemini.py, claude.py, ollama.py
Lazy-import providers so a missing SDK never breaks the app.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from core.contracts import (LLMMessage, LLMResponse, LLMUsage, Role, ToolCall, ToolSpec)
from llm.providers.base import BaseProvider, ProviderUnavailableError

_ROLE_MAP = {Role.SYSTEM: "system", Role.USER: "user", Role.ASSISTANT: "model", Role.TOOL: "user"}


class GeminiProvider(BaseProvider):
    name = "gemini"

    async def chat(self, messages, tools=None, **kw) -> LLMResponse:
        try:
            from google import genai  # noqa: F401
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailableError(f"google-genai SDK missing: {e}")
        from google.genai import types

        system = [m.content for m in messages if m.role == Role.SYSTEM and m.content]
        parts = []
        for m in messages:
            if m.role == Role.SYSTEM:
                continue
            role = "model" if m.role in (Role.ASSISTANT, Role.TOOL) else "user"
            if m.tool_calls:
                fparts = []
                for tc in m.tool_calls:
                    fparts.append(types.FunctionCall(name=tc.name, args=tc.arguments))
                parts.append(types.Content(role=role, parts=fparts))
            else:
                parts.append(types.Content(role=role, parts=[types.Part(text=m.content or "")]))

        client_kwargs: dict[str, Any] = {}
        if self.api_key:
            client_kwargs["api_key"] = self.api_key
        from google import genai as _genai
        client = _genai.Client(**client_kwargs)

        config = types.GenerateContentConfig(
            system_instruction=system or None,
            temperature=kw.get("temperature", self.temperature),
            max_output_tokens=kw.get("max_tokens", self.max_tokens),
        )
        if tools:
            config.tools = [types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name=t.name, description=t.description,
                    parameters=types.Schema(**t.parameters) if t.parameters else None)
                for t in tools])]
        try:
            resp = client.models.generate_content(model=self.model, contents=parts, config=config)
        except Exception as e:  # noqa: BLE001
            raise self.classify_error(e)

        content = resp.text if resp.text else None
        tool_calls = []
        try:
            for cand in resp.candidates or []:
                for part in cand.content.parts or []:
                    if part.function_call:
                        tool_calls.append(ToolCall(id=part.function_call.id or "gc",
                                                   name=part.function_call.name,
                                                   arguments=dict(part.function_call.args or {})))
        except Exception:
            pass
        return LLMResponse(content=content, tool_calls=tool_calls, provider=self.name,
                           model=self.model, usage=LLMUsage())

    async def stream(self, messages, **kw) -> AsyncIterator[str]:
        resp = await self.chat(messages, **kw)
        if resp.content:
            yield resp.content

    async def embed(self, text: str) -> list[float]:
        raise ProviderUnavailableError("gemini embeddings not configured")


class ClaudeProvider(BaseProvider):
    name = "claude"

    async def chat(self, messages, tools=None, **kw) -> LLMResponse:
        try:
            import anthropic
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailableError(f"anthropic SDK missing: {e}")
        client = anthropic.AsyncAnthropic(api_key=self.api_key or "not-set")

        system = "\n".join(m.content or "" for m in messages if m.role == Role.SYSTEM and m.content) or None
        conv = []
        for m in messages:
            if m.role == Role.SYSTEM:
                continue
            role = "assistant" if m.role in (Role.ASSISTANT, Role.TOOL) else "user"
            conv.append({"role": role, "content": m.content or ""})
        native_tools = None
        if tools:
            native_tools = [{
                "name": t.name, "description": t.description,
                "input_schema": t.parameters,
            } for t in tools]
        try:
            resp = await client.messages.create(
                model=self.model, max_tokens=kw.get("max_tokens", self.max_tokens),
                temperature=kw.get("temperature", self.temperature),
                system=system, messages=conv, tools=native_tools)
        except Exception as e:  # noqa: BLE001
            raise self.classify_error(e)
        tool_calls = []
        content = None
        for block in resp.content:
            if block.type == "text":
                content = (content or "") + block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name,
                                           arguments=dict(block.input or {})))
        usage = LLMUsage(prompt_tokens=resp.usage.input_tokens,
                         completion_tokens=resp.usage.output_tokens,
                         total_tokens=resp.usage.input_tokens + resp.usage.output_tokens)
        return LLMResponse(content=content, tool_calls=tool_calls, usage=usage,
                           provider=self.name, model=self.model)

    async def stream(self, messages, **kw) -> AsyncIterator[str]:
        resp = await self.chat(messages, **kw)
        if resp.content:
            yield resp.content

    async def embed(self, text: str) -> list[float]:
        raise ProviderUnavailableError("claude embeddings not configured")


class OllamaProvider(BaseProvider):
    name = "ollama"

    async def chat(self, messages, tools=None, **kw) -> LLMResponse:
        import httpx
        base = self.base_url or "http://localhost:11434"
        conv = []
        for m in messages:
            conv.append({"role": m.role.value, "content": m.content or ""})
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(f"{base}/api/chat", json={
                    "model": self.model, "messages": conv, "stream": False,
                    "options": {"temperature": kw.get("temperature", self.temperature)},
                })
                r.raise_for_status()
                data = r.json()
        except Exception as e:  # noqa: BLE001
            raise self.classify_error(e)
        return LLMResponse(content=data.get("message", {}).get("content"), provider=self.name,
                           model=self.model, usage=LLMUsage())

    async def stream(self, messages, **kw) -> AsyncIterator[str]:
        resp = await self.chat(messages, **kw)
        if resp.content:
            yield resp.content

    async def embed(self, text: str) -> list[float]:
        raise ProviderUnavailableError("ollama embeddings not configured")
