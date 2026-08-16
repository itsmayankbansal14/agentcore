"""AgentCore — observer/workflow_observers.py
Observers for the capability workflows. Each VERIFIES a real effect:
  - Filesystem: file exists / content hash matches
  - Browser   : current URL matches expected
  - Windows   : process alive / exited (real process state)
  - Android   : handled by ScreenObserver (screenshot + vision) already
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from observer.base import Observation, Observer


class FilesystemWorkflowObserver(Observer):
    source = "fs_workflow"

    def __init__(self, sandbox_root: str | Path) -> None:
        self.sandbox = Path(sandbox_root).resolve()

    def verify(self, tool_name, args, result) -> list[Observation]:
        if tool_name == "fs_write_content":
            p = (self.sandbox / (args.get("path") or "")).resolve()
            exists = p.exists()
            return [Observation(source=self.source, ok=exists,
                                data={"file": str(p), "exists": exists,
                                      "size": p.stat().st_size if exists else None},
                                message=f"file {'exists' if exists else 'missing'}: {p.name}")]
        if tool_name == "fs_verify_integrity":
            # the tool already verified; observer confirms the hash independently
            p = (self.sandbox / (args.get("path") or "")).resolve()
            expected = args.get("expected_content", "")
            if p.is_file() and expected:
                actual = p.read_text(encoding="utf-8", errors="replace")
                ok = actual == expected
                return [Observation(source=self.source, ok=ok,
                                    data={"file": str(p), "content_match": ok},
                                    message=f"integrity {'verified' if ok else 'MISMATCH'}: {p.name}")]
        if tool_name == "fs_delete":
            p = (self.sandbox / (args.get("path") or "")).resolve()
            gone = not p.exists()
            return [Observation(source=self.source, ok=gone,
                                data={"file": str(p), "deleted": gone},
                                message=f"file {'deleted' if gone else 'still present'}: {p.name}")]
        return []


class BrowserWorkflowObserver(Observer):
    source = "browser"

    def verify(self, tool_name, args, result) -> list[Observation]:
        if tool_name == "browser_verify_url":
            data = dict(result or {})  # verify_after passes the data dict directly
            ok = bool(data.get("match"))
            return [Observation(source=self.source, ok=ok,
                                data={"current": data.get("current"),
                                      "expected": data.get("expected")},
                                message=("URL verified ✓" if ok
                                         else f"URL mismatch: {data.get('current')}"))]
        return []


class WindowsWorkflowObserver(Observer):
    source = "windows"

    def verify(self, tool_name, args, result) -> list[Observation]:
        if tool_name == "win_detect_open":
            data = dict(result or {})  # verify_after passes the data dict directly
            ok = bool(data.get("open"))
            return [Observation(source=self.source, ok=ok,
                                data={"app": data.get("app"), "pid": data.get("pid")},
                                message="app open ✓" if ok else "app did not open")]
        if tool_name == "win_verify_closed":
            data = dict(result or {})
            ok = bool(data.get("closed"))
            return [Observation(source=self.source, ok=ok,
                                data={"pid": data.get("pid")},
                                message="app closed ✓" if ok else "app still running")]
        return []


def register_workflow_observers(mgr, sandbox_root: str | Path) -> None:
    mgr.register(FilesystemWorkflowObserver(sandbox_root))
    mgr.register(BrowserWorkflowObserver())
    mgr.register(WindowsWorkflowObserver())
