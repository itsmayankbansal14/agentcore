"""AgentCore — memory/personal.py
Personal Knowledge (intentional memory) — what the USER wants AgentCore to
remember: ideas, websites, resources, projects, notes, discoveries.

Distinct from task/working memory ("what is AgentCore currently doing").
Every record is structured (kind, title, url, description, purpose, usage,
tags, notes, status, created_at) and stored in SQLite — never in chat history.

`briefing()` is the startup/briefing surface: concise, never a dump.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from database.connection import Database
from database.models import SavedItem

log = structlog.get_logger("agentcore.memory.personal")

KINDS = ("website", "idea", "resource", "project", "note", "discovery")
STATUSES = ("new", "review", "active", "archived")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def parse_tags(raw: str | list[str] | None) -> str:
    """Normalize tags (comma or space separated list) to a comma string."""
    if not raw:
        return ""
    if isinstance(raw, list):
        parts = [str(t).strip().lower() for t in raw]
    else:
        parts = [t.strip().lower() for t in re.split(r"[,;]", str(raw))]
    return ", ".join(p for p in parts if p)


def split_tags(raw: str) -> list[str]:
    return [t.strip() for t in str(raw or "").split(",") if t.strip()]


class PersonalMemory:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- write ------------------------------------------------------------
    def save(self, kind: str, title: str, *, url: str = "",
             description: str = "", purpose: str = "", usage: str = "",
             tags: str | list[str] | None = None, notes: str = "",
             status: str = "new", related_project: str = "") -> int:
        kind = kind.lower()
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}; use one of {KINDS}")
        status = status.lower() if status in STATUSES else "new"
        with self.db.session() as s:
            item = SavedItem(kind=kind, title=title.strip(), url=(url or "").strip(),
                             description=description.strip(),
                             purpose=purpose.strip(), usage=usage.strip(),
                             tags=parse_tags(tags), notes=notes.strip(),
                             status=status, related_project=related_project or "")
            s.add(item)
            s.commit()
            log.info("personal item saved", kind=kind, title=title[:60],
                     id=item.id, status=status)
            return item.id

    def remove(self, item_id: int) -> bool:
        with self.db.session() as s:
            item = s.get(SavedItem, item_id)
            if item is None:
                return False
            s.delete(item)
            s.commit()
            return True

    def update_status(self, item_id: int, status: str) -> bool:
        if status not in STATUSES:
            return False
        with self.db.session() as s:
            item = s.get(SavedItem, item_id)
            if item is None:
                return False
            item.status = status
            s.commit()
            return True

    # -- read -------------------------------------------------------------
    def list(self, kind: str | None = None, tag: str | None = None,
             status: str | None = None, limit: int = 50) -> list[dict]:
        with self.db.session() as s:
            q = s.query(SavedItem)
            if kind:
                q = q.filter(SavedItem.kind == kind.lower())
            if status:
                q = q.filter(SavedItem.status == status.lower())
            if tag:
                q = q.filter(SavedItem.tags.like(f"%{tag.lower()}%"))
            rows = q.order_by(SavedItem.created_at.desc()).limit(limit).all()
            return [self._to_dict(r) for r in rows]

    def recent(self, days: int = 7, limit: int = 20) -> list[dict]:
        cutoff = _iso(_now_utc() - timedelta(days=days))
        with self.db.session() as s:
            rows = (s.query(SavedItem)
                    .filter(SavedItem.created_at >= cutoff)
                    .order_by(SavedItem.created_at.desc()).limit(limit).all())
            return [self._to_dict(r) for r in rows]

    def needs_review(self, limit: int = 10) -> list[dict]:
        with self.db.session() as s:
            rows = (s.query(SavedItem)
                    .filter(SavedItem.status.in_(["review", "new"]))
                    .order_by(SavedItem.created_at.asc()).limit(limit).all())
            return [self._to_dict(r) for r in rows]

    def count(self) -> dict[str, int]:
        from sqlalchemy import func
        with self.db.session() as s:
            rows = (s.query(SavedItem.kind, func.count(SavedItem.id))
                    .group_by(SavedItem.kind).all())
            return dict(rows or [])

    # -- briefing ----------------------------------------------------------
    def briefing(self, active_project: str | None = None,
                 active_project_tags: list[str] | None = None) -> str:
        """Concise personal briefing — recent ideas, recent websites/discoveries,
        items explicitly related via related_project, items needing review.
        NEVER a dump. Uses explicit related_project first, then optional tags."""
        recent = self.recent(days=7, limit=30)
        lines: list[str] = []
        ideas = [r for r in recent if r["kind"] == "idea"]
        web = [r for r in recent if r["kind"] in ("website", "discovery", "resource")]
        notes = [r for r in recent if r["kind"] == "note"]

        if ideas:
            lines.append(f"You saved {len(ideas)} idea{'s' if len(ideas)>1 else ''} recently"
                         f" — most relevant: “{ideas[0]['title']}”.")
        if web:
            lines.append(f"{len(web)} website/discovery item{'s' if len(web)>1 else ''} saved recently"
                         f" — “{web[0]['title']}”"
                         + (f" ({web[0]['url']})" if web[0].get("url") else "") + ".")

        # 1) Explicit related_project match (preferred)
        if active_project:
            related_explicit = [r for r in recent
                                if r.get("related_project", "").lower() == active_project.lower()]
            if related_explicit:
                lines.append(f"{len(related_explicit)} saved item{'s' if len(related_explicit)>1 else ''} "
                             f"related to your active project “{active_project}” — "
                             f"“{related_explicit[0]['title']}”.")

        # 2) Fallback: items tagged with active project tags (optional)
        if active_project_tags:
            active_tags = [t.lower() for t in active_project_tags]
            related_tags = [r for r in recent if any(
                t in active_tags for t in split_tags(r.get("tags", "")))]
            if related_tags and not any("related to your active project" in line for line in lines):
                lines.append(f"{len(related_tags)} saved item{'s' if len(related_tags)>1 else ''} relate to your"
                             f" active work — “{related_tags[0]['title']}”.")

        # explicitly flagged for review (any age)
        review = self.needs_review(limit=5)
        flagged = [r for r in review if r["status"] == "review"]
        if flagged:
            lines.append(f"{len(flagged)} item{'s' if len(flagged)>1 else ''} waiting for your"
                         f" review — e.g. “{flagged[0]['title']}”.")
        if notes:
            lines.append(f"{len(notes)} note{'s' if len(notes)>1 else ''} saved recently.")
        if not lines:
            lines.append("Nothing saved yet — tell me “save this idea…” or “save this website…” "
                         "and I'll remember it.")
        return " ".join(lines)

    @staticmethod
    def _to_dict(r: SavedItem) -> dict[str, Any]:
        return {"id": r.id, "kind": r.kind, "title": r.title, "url": r.url,
                "description": r.description, "purpose": r.purpose,
                "usage": r.usage, "tags": split_tags(r.tags),
                "notes": r.notes, "status": r.status, "created_at": r.created_at}


def func_count():
    from sqlalchemy import func
    return func.count(SavedItem.id)
