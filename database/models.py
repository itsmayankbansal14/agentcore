"""AgentCore — database/models.py
Full schema per design doc §6. Every table the agent needs for
memory layers, task state, provider rotation, devices, audit.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (Boolean, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, JSON)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .connection import Base


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------ sessions
class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[str] = mapped_column(String, default=now)
    last_active: Mapped[str] = mapped_column(String, default=now)

    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    plans = relationship("Plan", back_populates="session", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    title: Mapped[str] = mapped_column(String, default="")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(String, default="main")
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON
    tool_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String, default=now, index=True)

    session = relationship("Session", back_populates="messages")


# ------------------------------------------------------------------ working
class WorkingMemory(Base):
    __tablename__ = "working_memory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), unique=True)
    current_task: Mapped[str] = mapped_column(Text, default="")
    current_plan_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_step_id: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(Text, default="{}")   # JSON checkpoint
    updated_at: Mapped[str] = mapped_column(String, default=now)


# ------------------------------------------------------------------ plans
class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="ACTIVE")  # ACTIVE|COMPLETED|ABANDONED
    created_at: Mapped[str] = mapped_column(String, default=now)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)

    session = relationship("Session", back_populates="plans")
    steps = relationship("PlanStep", back_populates="plan", cascade="all, delete-orphan",
                         order_by="PlanStep.order_idx")


class PlanStep(Base):
    __tablename__ = "plan_steps"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), index=True)
    parent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    # PENDING|RUNNING|WAITING_TOOL|BLOCKED|DONE|FAILED|INTERRUPTED
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint: Mapped[str] = mapped_column(Text, default="{}")
    order_idx: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String, default=now)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)

    plan = relationship("Plan", back_populates="steps")


# ------------------------------------------------------------------ LTM
class LongTermMemory(Base):
    __tablename__ = "long_term_memory"
    __table_args__ = (UniqueConstraint("session_id", "kind", "key", name="uq_ltm"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)      # preference|fact|project|identity
    key: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String, default="")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    updated_at: Mapped[str] = mapped_column(String, default=now)


# ------------------------------------------------------------------ knowledge
class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String, default="")
    mime: Mapped[str] = mapped_column(String, default="")
    sha256: Mapped[str] = mapped_column(String, default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    indexed_at: Mapped[str] = mapped_column(String, default=now)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[bytes | None] = mapped_column(nullable=True)  # optional vector


# ------------------------------------------------------------------ LLM state
class LLMProviderState(Base):
    __tablename__ = "llm_providers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, unique=True)
    model: Mapped[str] = mapped_column(String, default="")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    cooldown_until: Mapped[str | None] = mapped_column(String, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_used_at: Mapped[str | None] = mapped_column(String, nullable=True)


# ------------------------------------------------------------------ tool audit
class ToolExecution(Base):
    __tablename__ = "tool_executions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    plan_step_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tool: Mapped[str] = mapped_column(String, index=True)
    args: Mapped[str] = mapped_column(Text, default="{}")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="ok")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[str] = mapped_column(String, default=now)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)


class Execution(Base):
    """Persistent execution history per plan-step run (audit/debug/rollback)."""
    __tablename__ = "executions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    plan_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    step_id: Mapped[str | None] = mapped_column(String, nullable=True)
    goal: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="RUNNING")
    tool_calls: Mapped[str] = mapped_column(Text, default="[]")   # JSON
    errors: Mapped[str] = mapped_column(Text, default="[]")       # JSON
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[str] = mapped_column(String, default=now)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)


# ------------------------------------------------------------------ devices
class Device(Base):
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String)
    fingerprint: Mapped[str] = mapped_column(String, unique=True)
    device_token_hash: Mapped[str] = mapped_column(String, default="")
    last_seen: Mapped[str | None] = mapped_column(String, nullable=True)
    connection_state: Mapped[str] = mapped_column(String, default="offline")
    capabilities: Mapped[str] = mapped_column(Text, default="{}")  # JSON


class DeviceCommand(Base):
    __tablename__ = "device_commands"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"))
    cmd: Mapped[str] = mapped_column(String)
    params: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String, default="queued")
    envelope_id: Mapped[str] = mapped_column(String, default="")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=now)
    executed_at: Mapped[str | None] = mapped_column(String, nullable=True)


# ------------------------------------------------------------------ audit + kv
class AuditEntry(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String, default=now)
    actor: Mapped[str] = mapped_column(String, default="agent")
    action: Mapped[str] = mapped_column(String, index=True)
    target: Mapped[str] = mapped_column(String, default="")
    detail: Mapped[str] = mapped_column(Text, default="{}")


class ConfigKV(Base):
    __tablename__ = "config_kv"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[str] = mapped_column(String, default=now)


# ------------------------------------------------------------------ life data
# (carried over from the JARVIS prototype; JSON files migrate into these in Phase 3)
class Todo(Base):
    __tablename__ = "todos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String, default="medium")
    category: Mapped[str] = mapped_column(String, default="general")
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String, default=now)


class Habit(Base):
    __tablename__ = "habits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String)
    frequency: Mapped[str] = mapped_column(String, default="daily")
    streak: Mapped[int] = mapped_column(Integer, default=0)
    history: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of dates
    created_at: Mapped[str] = mapped_column(String, default=now)


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    amount: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String, default="general")
    note: Mapped[str] = mapped_column(String, default="")
    date: Mapped[str] = mapped_column(String, default=now)
