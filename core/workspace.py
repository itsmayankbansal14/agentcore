"""AgentCore — core/workspace.py
WorkspaceManager — the SINGLE authority for filesystem locations.

Every storage backend (tools, observers, TTS, adb keys, DB, logs, temp,
exports) MUST request paths through this manager instead of constructing
absolute paths. The Planner never references paths at all — it reasons about
capabilities; storage implementations stay interchangeable behind it.

Locations:
  root        workspace root
  data        application data (db, sandbox, screenshots, caches)
  logs        structured logs
  db          the SQLite database file
  tmp         temporary files (cleaned on start)
  exports     user-facing exports
  sandbox     tool filesystem sandbox
  screenshots captured screenshots
  adb         adb auth keys
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


class WorkspaceManager:
    def __init__(self, root: str | Path, *, data_name: str = "data") -> None:
        self.root = Path(root).resolve()
        self.data = self.root / data_name
        self.logs = self.root / "logs"
        self.tmp = self.data / "tmp"
        self.exports = self.root / "exports"
        self.sandbox = self.data / "sandbox"
        self.screenshots = self.data / "screenshots"
        self.adb = self.data / "adb"
        self.db_file = self.data / "agentcore.db"
        self.tts_cache = self.data / "tts_cache"
        self._ensure_all()

    def _ensure_all(self) -> None:
        for d in (self.data, self.logs, self.tmp, self.exports, self.sandbox,
                  self.screenshots, self.adb, self.tts_cache):
            d.mkdir(parents=True, exist_ok=True)

    # -- public path API -----------------------------------------------------
    def dir(self, name: str) -> Path:
        """Request a managed directory by logical name."""
        d = getattr(self, name, None)
        if d is None or not isinstance(d, Path):
            raise KeyError(f"unknown workspace location: {name}")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def path(self, name: str, *parts: str) -> Path:
        """Request a path inside a managed directory (e.g. path('sandbox','x.txt'))."""
        base = self.dir(name)
        p = base.joinpath(*parts)
        if not str(p.resolve()).startswith(str(base.resolve())):
            raise PermissionError(f"path escapes workspace location: {name}")
        return p

    def db_path(self) -> Path:
        return self.db_file

    def clean_tmp(self) -> None:
        """Clear the temp directory (startup hygiene)."""
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict[str, str]:
        return {name: str(getattr(self, name)) for name in
                ("root", "data", "logs", "tmp", "exports", "sandbox",
                 "screenshots", "adb", "db_file", "tts_cache")}
