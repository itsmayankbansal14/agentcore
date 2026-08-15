"""AgentCore — tools/workflows/fs_workflow.py
Filesystem workflow (REAL, every platform):
  create folder → create file → write content → read content → verify integrity → delete file.

All operations hit the real filesystem inside the sandbox root (the same
sandbox the fs_* tools use). Verification uses a real SHA-256 of the content.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from core.contracts import ToolResult
from tools.base import Tool


class _FsWorkflowBase(Tool):
    capability = "workflow.filesystem"

    def __init__(self, sandbox_root: str | Path) -> None:
        self.sandbox = Path(sandbox_root).resolve()

    def _resolve(self, rel: str) -> Path:
        p = (self.sandbox / rel.lstrip("/\\")).resolve()
        if not str(p).startswith(str(self.sandbox)):
            raise PermissionError(f"path escapes sandbox: {rel}")
        return p


class FSCreateFolder(_FsWorkflowBase):
    name = "fs_create_folder"
    description = "Create a folder inside the sandbox."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}},
                  "required": ["path"]}
    idempotent = True

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        p = self._resolve(params["path"])
        p.mkdir(parents=True, exist_ok=True)
        return ToolResult(ok=True, data={"folder": str(p), "exists": p.is_dir()})


class FSCreateFile(_FsWorkflowBase):
    name = "fs_create_file"
    description = "Create an empty file inside the sandbox."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}},
                  "required": ["path"]}
    idempotent = True

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        p = self._resolve(params["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch(exist_ok=True)
        return ToolResult(ok=True, data={"file": str(p), "bytes": p.stat().st_size})


class FSWriteFile(_FsWorkflowBase):
    name = "fs_write_content"
    description = "Write text content to a file inside the sandbox (overwrites)."
    parameters = {"type": "object",
                  "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                  "required": ["path", "content"]}

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        p = self._resolve(params["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(params["content"], encoding="utf-8")
        return ToolResult(ok=True, data={"file": str(p), "bytes": p.stat().st_size})


class FSReadFile(_FsWorkflowBase):
    name = "fs_read_content"
    description = "Read the content of a file inside the sandbox."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}},
                  "required": ["path"]}
    idempotent = True

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        p = self._resolve(params["path"])
        if not p.is_file():
            return ToolResult(ok=False, error=f"not a file: {p}")
        return ToolResult(ok=True, data={"file": str(p), "content": p.read_text(encoding="utf-8")})


class FSVerifyIntegrity(_FsWorkflowBase):
    name = "fs_verify_integrity"
    description = "Verify a file's content matches the expected SHA-256 hash."
    parameters = {"type": "object",
                  "properties": {"path": {"type": "string"},
                                 "expected_sha256": {"type": "string"},
                                 "expected_content": {"type": "string"}},
                  "required": ["path"]}
    idempotent = True

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        p = self._resolve(params["path"])
        if not p.is_file():
            return ToolResult(ok=False, error=f"file missing: {p}")
        data = p.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        ok = True
        detail = {"file": str(p), "sha256": actual, "bytes": len(data)}
        if params.get("expected_sha256"):
            ok = ok and actual == params["expected_sha256"]
            detail["sha256_match"] = actual == params["expected_sha256"]
        if params.get("expected_content"):
            ok = ok and data.decode("utf-8", "replace") == params["expected_content"]
            detail["content_match"] = data.decode("utf-8", "replace") == params["expected_content"]
        return ToolResult(ok=ok, data=detail)


class FSDeleteFile(_FsWorkflowBase):
    name = "fs_delete"
    description = "Delete a file inside the sandbox."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}},
                  "required": ["path"]}

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        p = self._resolve(params["path"])
        if p.exists():
            p.unlink()
        return ToolResult(ok=True, data={"file": str(p), "deleted": not p.exists()})


def register_all(registry, sandbox_root: str | Path) -> None:
    for t in (FSCreateFolder(sandbox_root), FSCreateFile(sandbox_root),
              FSWriteFile(sandbox_root), FSReadFile(sandbox_root),
              FSVerifyIntegrity(sandbox_root), FSDeleteFile(sandbox_root)):
        registry.register(t)
