"""AgentCore — memory/manager.py
Unified memory facade. Layers: STM (rolling window + budget), WM (task/plan/
step checkpoint), LTM (facts/prefs with confidence), Knowledge (docs/chunks
+ FTS5 lexical + vector semantic).

Canonical path per design §7: Conversation → DB → retrieve relevant history
→ summarize overflow → build prompt → LLM.
"""
from __future__ import annotations

import json
import logging
import structlog
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from config.manager import ConfigManager
from core.contracts import ContextBundle, LLMMessage, Role, ToolCall
from database.connection import Database
from database.models import (KnowledgeChunk, KnowledgeDocument, LongTermMemory,
                             Message, Session as DBSession, WorkingMemory)
from memory.extractor import extract_facts
from memory.indexer import KnowledgeIndexer
from memory.vector import VectorStore

log = structlog.get_logger("agentcore.memory")


class MemoryManager:
    def __init__(self, db: Database, config: ConfigManager, llm=None) -> None:
        self.db = db
        self.cfg = config
        self.llm = llm
        self.vector = VectorStore()
        self.indexer = KnowledgeIndexer(db, llm, self.vector) if llm else None
        self._load_vector()

    def _load_vector(self) -> None:
        try:
            with self.db.session() as s:
                rows = s.execute(
                    "SELECT id, embedding, '{}' FROM knowledge_chunks "
                    "WHERE embedding IS NOT NULL").all()
            self.vector.load([(r[0], r[1], r[2]) for r in rows])
        except Exception:  # noqa: BLE001
            log.debug("vector load skipped (empty or no FTS)")
            self.vector.clear()

    # ------------------------------------------------------------------ STM
    def store_message(self, session_id: str, msg: LLMMessage, provider: str = "",
                      model: str = "", tokens: int = 0) -> None:
        with self.db.session() as s:
            s.add(Message(
                session_id=session_id, role=msg.role.value, content=msg.content,
                tool_calls=json.dumps([tc.__dict__ for tc in msg.tool_calls]) if msg.tool_calls else None,
                tool_call_id=msg.tool_call_id, provider=provider, model=model, tokens=tokens,
            ))
            s.commit()

    def _load_messages(self, session_id: str, limit: int) -> list[Message]:
        with self.db.session() as s:
            rows = s.execute(
                select(Message).where(Message.session_id == session_id)
                .order_by(Message.id.desc()).limit(limit)
            ).scalars().all()
            return list(reversed(rows))

    def load_history(self, session_id: str, limit: int | None = None) -> list[LLMMessage]:
        limit = limit or self.cfg.get_int("memory.stm_window_messages", 20)
        out: list[LLMMessage] = []
        for row in self._load_messages(session_id, limit):
            tc = json.loads(row.tool_calls) if row.tool_calls else None
            out.append(LLMMessage(
                role=Role(row.role), content=row.content,
                tool_calls=[ToolCall(**t) for t in tc] if tc else None,
                tool_call_id=row.tool_call_id,
            ))
        return out

    async def summarize_overflow(self, session_id: str) -> str | None:
        """Compress the oldest messages into a synthetic summary (LLM, single pass)."""
        history = self.load_history(session_id, limit=60)
        if len(history) < 8:
            return None
        body = "\n".join(f"{m.role.value}: {m.content or ''}" for m in history[: len(history) - 4])
        try:
            if self.llm is None:
                raise RuntimeError("no llm")
            resp = await self.llm.chat([
                LLMMessage(role=Role.SYSTEM,
                           content="Summarize this conversation's important facts and "
                                   "context in 2-3 sentences. Be factual and concise."),
                LLMMessage(role=Role.USER, content=body[:4000]),
            ])
            summary = (resp.content or "").strip()
            if not summary:
                return None
            # store the summary as a synthetic system message at the oldest position
            with self.db.session() as s:
                rows = s.execute(select(Message).where(Message.session_id == session_id)
                                 .order_by(Message.id).limit(len(history) - 4)).scalars().all()
                for row in rows:
                    s.delete(row)
                first = s.execute(select(Message).where(Message.session_id == session_id)
                                  .order_by(Message.id).limit(1)).scalar_one_or_none()
                summary_msg = Message(
                    session_id=session_id, role="system",
                    content=f"[compacted summary of earlier conversation] {summary}",
                    provider="memory", tokens=len(summary) // 4,
                )
                # keep ordering sane: insert before the earliest remaining message
                if first is not None:
                    summary_msg.id = first.id  # reuse the earliest id slot (simplest stable order)
                s.add(summary_msg)
                s.commit()
            return summary
        except Exception as e:  # noqa: BLE001
            log.debug("summarize overflow failed", error=str(e))
            return None

    async def ensure_budget(self, session_id: str, max_messages: int) -> None:
        """Keep history within budget: summarize oldest if over."""
        count = len(self.load_history(session_id, limit=max_messages + 20))
        if count > max_messages:
            await self.summarize_overflow(session_id)

    # ------------------------------------------------------------------ WM
    def update_working(self, session_id: str, *, task: str | None = None,
                       plan_id: str | None = None, step_id: str | None = None,
                       state: dict[str, Any] | None = None) -> None:
        with self.db.session() as s:
            wm = s.execute(select(WorkingMemory).where(
                WorkingMemory.session_id == session_id)).scalar_one_or_none()
            if wm is None:
                wm = WorkingMemory(session_id=session_id)
                s.add(wm)
            if task is not None:
                wm.current_task = task
            if plan_id is not None:
                wm.current_plan_id = plan_id
            if step_id is not None:
                wm.current_step_id = step_id
            if state is not None:
                wm.state = json.dumps(state)
            wm.updated_at = datetime.now(timezone.utc).isoformat()
            s.commit()

    def load_working(self, session_id: str) -> dict[str, Any]:
        with self.db.session() as s:
            wm = s.execute(select(WorkingMemory).where(
                WorkingMemory.session_id == session_id)).scalar_one_or_none()
            if wm is None:
                return {}
            try:
                state = json.loads(wm.state or "{}")
            except Exception:
                state = {}
            return {
                "current_task": wm.current_task,
                "current_plan_id": wm.current_plan_id,
                "current_step_id": wm.current_step_id,
                "state": state,
            }

    # ------------------------------------------------------------------ LTM
    def remember(self, session_id: str, kind: str, key: str, content: str,
                 source: str = "", confidence: float = 1.0) -> None:
        with self.db.session() as s:
            row = s.execute(select(LongTermMemory).where(
                LongTermMemory.session_id == session_id,
                LongTermMemory.kind == kind,
                LongTermMemory.key == key)).scalar_one_or_none()
            if row is None:
                row = LongTermMemory(session_id=session_id, kind=kind, key=key)
                s.add(row)
            row.content = content
            row.source = source
            row.confidence = max(row.confidence if row.confidence else 0.0, confidence)
            row.updated_at = datetime.now(timezone.utc).isoformat()
            s.commit()

    def remember_from_message(self, session_id: str, message: str) -> int:
        """Extract + store facts from a user message. Returns count stored."""
        facts = extract_facts(message)
        for kind, key, content, conf in facts:
            self.remember(session_id, kind, key, content,
                          source="extracted", confidence=conf)
        return len(facts)

    def recall(self, session_id: str, kinds: list[str] | None = None,
               top_k: int | None = None) -> list[str]:
        k = top_k or self.cfg.get_int("memory.ltm_top_k", 8)
        with self.db.session() as s:
            q = select(LongTermMemory).where(LongTermMemory.session_id == session_id)
            if kinds:
                q = q.where(LongTermMemory.kind.in_(kinds))
            rows = s.execute(q).scalars().all()
            # rank: confidence desc, then recency
            rows = sorted(rows, key=lambda r: (r.confidence, r.updated_at), reverse=True)
            return [f"{r.kind}: {r.key} = {r.content} (conf {r.confidence:.2f})"
                    for r in rows[:k]]

    def consolidate(self, min_confidence: float = 0.4,
                    max_age_days: float = 180.0) -> int:
        """Confidence decay + prune stale low-confidence facts. Returns pruned count."""
        pruned = 0
        with self.db.session() as s:
            rows = s.execute(select(LongTermMemory)).scalars().all()
            for r in rows:
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(r.updated_at)).days
                except Exception:
                    age = 0
                if age > max_age_days or r.confidence < min_confidence:
                    s.delete(r)
                    pruned += 1
            s.commit()
        return pruned

    # ------------------------------------------------------------------ knowledge
    async def add_knowledge(self, path: str) -> dict:
        if self.indexer is None:
            return {"ok": False, "error": "knowledge indexer not available"}
        return await self.indexer.ingest_file(path)

    async def add_knowledge_dir(self, path: str) -> dict:
        if self.indexer is None:
            return {"ok": False, "error": "knowledge indexer not available"}
        return await self.indexer.ingest_dir(path)

    async def search_knowledge(self, query: str, top_k: int | None = None) -> list[str]:
        if self.indexer is None:
            return []
        k = top_k or self.cfg.get_int("memory.knowledge_top_k", 5)
        hits = await self.indexer.search(query, top_k=k)
        return [f"[{h['doc']}] {h['content']}" for h in hits]

    def _sync_fts(self) -> None:
        try:
            with self.db.engine.begin() as conn:
                conn.exec_driver_sql(
                    "INSERT OR IGNORE INTO knowledge_fts(rowid, content) "
                    "SELECT id, content FROM knowledge_chunks")
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ context assembly
    async def load_context(self, session_id: str, user_message: str | None = None) -> ContextBundle:
        budget = self.cfg.get_int("llm.max_context_messages", 40)
        await self.ensure_budget(session_id, budget)
        history = self.load_history(session_id)
        working = self.load_working(session_id)
        ltm = self.recall(session_id)
        knowledge = await self.search_knowledge(user_message) if user_message else []
        return ContextBundle(history=history, working=working,
                             ltm_facts=ltm, knowledge=knowledge)
