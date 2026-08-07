"""AgentCore — tools/local/filesystem.py
Sandboxed filesystem tools. All paths resolve inside the configured sandbox
root so the agent can't wander the whole machine (production safety default).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.contracts import ToolResult
from tools.base import Tool


class _FsTool(Tool):
    capability = "filesystem"

    def __init__(self, sandbox_root: str) -> None:
        self.sandbox = Path(sandbox_root).resolve()

    def _resolve(self, rel: str) -> Path | None:
        p = (self.sandbox / rel.lstrip("/\\")).resolve()
        if not str(p).startswith(str(self.sandbox)):
            return None
        return p


class ReadFileTool(_FsTool):
    name = "fs_read"
    description = "Read a text file from the sandbox. Path is relative to the sandbox root."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    idempotent = True

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        p = self._resolve(params.get("path", ""))
        if p is None:
            return ToolResult(ok=False, error="path escapes sandbox")
        if not p.exists() or not p.is_file():
            return ToolResult(ok=False, error=f"not a file: {params.get('path')}")
        content = p.read_text(encoding="utf-8", errors="replace")
        return ToolResult(ok=True, data={"path": str(p), "content": content[:4000],
                                         "size": len(content)})


class WriteFileTool(_FsTool):
    name = "fs_write"
    description = "Write a text file inside the sandbox. Creates parent directories."
    parameters = {"type": "object",
                  "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                  "required": ["path", "content"]}

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        p = self._resolve(params.get("path", ""))
        if p is None:
            return ToolResult(ok=False, error="path escapes sandbox")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(params.get("content", ""), encoding="utf-8")
        return ToolResult(ok=True, data={"path": str(p), "bytes": p.stat().st_size})


class ListDirTool(_FsTool):
    name = "fs_list"
    description = "List files and folders in a sandbox directory."
    parameters = {"type": "object",
                  "properties": {"path": {"type": "string", "default": "."}},
                  "required": []}
    idempotent = True

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        p = self._resolve(params.get("path", "."))
        if p is None:
            return ToolResult(ok=False, error="path escapes sandbox")
        if not p.exists() or not p.is_dir():
            return ToolResult(ok=False, error=f"not a dir: {params.get('path')}")
        items = sorted([{"name": x.name, "is_dir": x.is_dir(), "size": x.stat().st_size if x.is_file() else None}
                        for x in p.iterdir()], key=lambda i: (not i["is_dir"], i["name"]))
        return ToolResult(ok=True, data={"path": str(p), "items": items[:100], "count": len(items)})


def register_all(registry, sandbox_root: str) -> None:
    for tool in (ReadFileTool(sandbox_root), WriteFileTool(sandbox_root), ListDirTool(sandbox_root)):
        registry.register(tool)
