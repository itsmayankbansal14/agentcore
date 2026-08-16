"""AgentCore — tools/personal.py
Personal-knowledge tools: save websites/ideas/notes with structured fields,
list saved items, and produce the startup briefing. Backed by
memory.personal.PersonalMemory (SQLite) — real storage, no placeholders.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import requests

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BeautifulSoup = None
    BS4_AVAILABLE = False

from core.contracts import ToolResult
from tools.base import Tool


def _fetch_basic_website_metadata(url: str, timeout: float = 4.0) -> dict:
    """Lightweight, non-aggressive metadata fetch.
    Returns title, description, domain or empty values on failure.
    Never fabricates data."""
    result = {"title": "", "description": "", "domain": ""}
    if not BS4_AVAILABLE:
        # Graceful degradation when beautifulsoup4 is missing
        return result
    try:
        parsed = urlparse(url)
        if not parsed.scheme:
            url = "https://" + url
        headers = {"User-Agent": "AgentCore/1.0 (personal use)"}
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if resp.status_code != 200:
            return result
        soup = BeautifulSoup(resp.text, "html.parser")
        # title
        if soup.title and soup.title.string:
            result["title"] = soup.title.string.strip()[:200]
        # meta description
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            result["description"] = desc["content"].strip()[:300]
        result["domain"] = parsed.netloc or parsed.path
    except Exception:  # noqa: BLE001 — graceful failure, never block save
        pass
    return result

_KINDS = ("website", "idea", "resource", "project", "note", "discovery")


class SaveWebsiteTool(Tool):
    name = "save_website"
    description = ("Save a website to personal memory with name, URL, what it "
                   "is, and what you intend to use it for.")
    parameters = {"type": "object",
                  "properties": {
                      "url": {"type": "string"},
                      "name": {"type": "string"},
                      "description": {"type": "string"},
                      "purpose": {"type": "string"},
                      "usage": {"type": "string"},
                      "tags": {"type": "string"},
                      "notes": {"type": "string"},
                  },
                  "required": ["url"]}
    capability = "memory.personal"
    idempotent = False

    def __init__(self, personal) -> None:
        self.personal = personal

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        url = (params.get("url") or "").strip()
        if not url:
            return ToolResult(ok=False, error="save_website: url is required")

        # Auto-fetch basic metadata only when user did not provide name/description
        meta = {}
        if not params.get("name") and not params.get("description"):
            meta = _fetch_basic_website_metadata(url)

        name = (params.get("name") or meta.get("title") or url).strip()
        description = params.get("description") or meta.get("description", "")

        item_id = self.personal.save(
            "website", name, url=url,
            description=description,
            purpose=params.get("purpose", ""),
            usage=params.get("usage", ""),
            tags=params.get("tags", ""),
            notes=params.get("notes", ""),
        )
        return ToolResult(ok=True, data={"id": item_id, "kind": "website",
                                         "name": name, "url": url})


class SaveIdeaTool(Tool):
    name = "save_idea"
    description = "Save an idea to personal memory (title + optional details)."
    parameters = {"type": "object",
                  "properties": {
                      "title": {"type": "string"},
                      "description": {"type": "string"},
                      "tags": {"type": "string"},
                      "notes": {"type": "string"},
                  },
                  "required": ["title"]}
    capability = "memory.personal"
    idempotent = False

    def __init__(self, personal) -> None:
        self.personal = personal

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        title = (params.get("title") or "").strip()
        if not title:
            return ToolResult(ok=False, error="save_idea: title is required")
        item_id = self.personal.save(
            "idea", title,
            description=params.get("description", ""),
            tags=params.get("tags", ""),
            notes=params.get("notes", ""),
        )
        return ToolResult(ok=True, data={"id": item_id, "kind": "idea",
                                         "title": title})


class SaveNoteTool(Tool):
    name = "save_note"
    description = "Save a note/discovery to personal memory."
    parameters = {"type": "object",
                  "properties": {"title": {"type": "string"},
                                 "body": {"type": "string"},
                                 "tags": {"type": "string"}},
                  "required": ["title"]}
    capability = "memory.personal"
    idempotent = False

    def __init__(self, personal) -> None:
        self.personal = personal

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        item_id = self.personal.save(
            "note", (params.get("title") or "").strip(),
            description=params.get("body", ""),
            tags=params.get("tags", ""),
        )
        return ToolResult(ok=True, data={"id": item_id, "kind": "note"})


class SavedListTool(Tool):
    name = "saved_list"
    description = "List items in personal memory (optionally by kind or tag)."
    parameters = {"type": "object",
                  "properties": {"kind": {"type": "string", "enum": list(_KINDS)},
                                 "tag": {"type": "string"},
                                 "limit": {"type": "integer"}},
                  "required": []}
    capability = "memory.personal"
    idempotent = True

    def __init__(self, personal) -> None:
        self.personal = personal

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        rows = self.personal.list(kind=params.get("kind"),
                                  tag=params.get("tag"),
                                  limit=int(params.get("limit") or 20))
        return ToolResult(ok=True, data={"count": len(rows), "items": rows})


class PersonalBriefingTool(Tool):
    name = "personal_briefing"
    description = ("Concise personal briefing: recent ideas, saved websites/"
                   "discoveries, items related to active work, items to review.")
    parameters = {"type": "object", "properties": {}}
    capability = "memory.personal"
    idempotent = True

    def __init__(self, personal, memory=None) -> None:
        self.personal = personal
        self.memory = memory   # MemoryManager for active-project context (optional)

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        active_project = None
        active_tags: list[str] = []
        if self.memory is not None:
            try:
                wm = self.memory.load_working(ctx.get("session_id", ""))
                task = wm.get("current_task") or ""
                # Do NOT treat the current task text as an active project.
                # Only use explicit related_project field set by the user.
                # active_tags still extracted for fallback tag matching.
                active_tags = [t.strip().lower() for t in task.split()
                               if len(t.strip()) > 2][:8]
            except Exception:  # noqa: BLE001
                active_tags = []
        brief = self.personal.briefing(active_project=active_project,
                                       active_project_tags=active_tags)
        return ToolResult(ok=True, data={"briefing": brief})


def register_all(registry, personal, memory=None) -> None:
    registry.register(SaveWebsiteTool(personal))
    registry.register(SaveIdeaTool(personal))
    registry.register(SaveNoteTool(personal))
    registry.register(SavedListTool(personal))
    registry.register(PersonalBriefingTool(personal, memory))
