"""AgentCore — tools/local/clipboard.py
Desktop clipboard tools (capability "clipboard").

Backed by pyperclip (added to requirements.txt). On systems with no real
clipboard (headless/SSH) the tools return a structured error — they NEVER
fabricate a success. On Windows (the primary target) pyperclip uses the
native Win32 clipboard, so set/get work without any extra setup.
"""
from __future__ import annotations

from typing import Any

from core.contracts import ToolResult
from tools.base import Tool


def _backend():
    """Return (set_text, get_text) callables or raise a clear RuntimeError."""
    try:
        import pyperclip
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"pyperclip not installed: {e}") from e
    return pyperclip.copy, pyperclip.paste


class ClipboardSetTool(Tool):
    name = "clipboard_set"
    description = "Copy text to the desktop clipboard."
    parameters = {"type": "object", "properties": {"text": {"type": "string"}},
                  "required": ["text"]}
    capability = "clipboard"
    idempotent = True

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        text = params.get("text", "")
        try:
            set_text, _ = _backend()
            set_text(text)
            return ToolResult(ok=True, data={"set": True, "chars": len(text)})
        except Exception as e:  # noqa: BLE001
            return ToolResult(ok=False,
                              error=f"clipboard_set: {e} (no display/clipboard here?)")


class ClipboardGetTool(Tool):
    name = "clipboard_get"
    description = "Read the current desktop clipboard text."
    parameters = {"type": "object", "properties": {}}
    capability = "clipboard"
    idempotent = True

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        try:
            _, get_text = _backend()
            return ToolResult(ok=True, data={"text": get_text() or ""})
        except Exception as e:  # noqa: BLE001
            return ToolResult(ok=False,
                              error=f"clipboard_get: {e} (no display/clipboard here?)")


def register_all(registry) -> None:
    registry.register(ClipboardSetTool())
    registry.register(ClipboardGetTool())
