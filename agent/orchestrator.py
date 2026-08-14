"""AgentCore — agent/orchestrator.py
Event-driven orchestrator. Coordinates — never implements business logic.

Owns: session lifecycle, plan lifecycle, context assembly policy, and the
decision of *which* step to hand the Executor. The Executor owns the actual
LLM↔tool loop, retries, timeouts, cancellation and execution history.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import structlog

from config.manager import ConfigManager
from core.bus import EventBus
from core.contracts import (ContextBundle, EventType, LLMMessage, Role)
from core.errors import FailureClass, classify, suggestions_for
from core.permissions import PermissionManager
from database.models import Session as DBSession
from devices.base import DeviceManager
from executor.executor import Executor, StepOutcome
from llm.manager import LLMManager
from memory.manager import MemoryManager
from observer.manager import ObserverManager
from planner.planner import Planner
from planner.steps import StepStatus
from tools.registry import ToolRegistry

log = structlog.get_logger("agentcore.agent")

SYSTEM_PROMPT_TEMPLATE = """You are {agent_name}, a desktop-first AI agent.
- You reason; the TOOL SYSTEM executes. You never touch files, devices, or memory directly.
- When a task needs action, call the appropriate tool and wait for the result.
- Be concise and concrete. Respond in the user's language.
- Current working task: {task}
- Active plan: {plan}
"""

# A follow-up that MODIFIES the active task (target switch / correction) rather
# than starting a new one. Only applies when a TaskState already exists.
_CONTINUATION_MARKERS = (
    r"\b(?:on|via|using|through|in)\s+(?:my|the|this)?\s*"
    r"(?:phone|android|mobile|device|browser|chrome|firefox|edge|"
    r"laptop|pc|computer|desktop|windows|this\s+pc)\b",
    r"\b(?:no\s*)?(?:wait|actually|instead|rather)\b",
    r"\b(?:do\s+it|yes|yeah|yep|ok|okay|go\s+ahead|sure)\b",
    r"\b(?:re\s*-?\s*run|again|retry|resume|keep\s+going|continue)\b",
)


class AgentOrchestrator:
    def __init__(self, config: ConfigManager, bus: EventBus, db,
                 memory: MemoryManager, llm: LLMManager, registry: ToolRegistry,
                 planner: Planner, devices: DeviceManager, executor: Executor,
                 observers: ObserverManager, permissions: PermissionManager,
                 target_resolver=None, task_state=None) -> None:
        self.cfg = config
        self.bus = bus
        self.db = db
        self.memory = memory
        self.llm = llm
        self.registry = registry
        self.planner = planner
        self.devices = devices
        self.executor = executor
        self.observers = observers
        self.permissions = permissions
        self.target_resolver = target_resolver
        self.task_state = task_state      # agent.task_state.TaskStateStore | None

        # event wiring — the orchestrator coordinates by reacting
        bus.subscribe(EventType.TOOL_RESULT, self._on_tool_result)

    # ------------------------------------------------------------------ sessions
    def ensure_session(self, session_id: str, name: str = "") -> None:
        with self.db.session() as s:
            if s.get(DBSession, session_id) is None:
                s.add(DBSession(id=session_id, name=name or session_id))
                s.commit()

    def _on_tool_result(self, ev) -> None:
        log.debug("tool result event", **ev.payload)

    # ------------------------------------------------------------------ context building
    def _build_system_prompt(self, session_id: str, plan) -> str:
        ctx = self.memory.load_working(session_id)
        plan_summary = self.planner.plan_summary(plan) if plan else ""
        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            agent_name=self.cfg.get_str("app.name", "AgentCore"),
            task=ctx.get("current_task", "") or "none",
            plan=plan_summary or "none",
        )
        facts = self.memory.recall(session_id, top_k=8)
        if facts:
            prompt += "\n\n" + "\n".join(f"KNOWN FACT: {f}" for f in facts[:8])
        return prompt

    # ------------------------------------------------------------------ main entry
    async def handle_user_message(self, session_id: str, text: str) -> str:
        self.ensure_session(session_id)
        self.bus.emit(EventType.USER_MESSAGE_RECEIVED,
                      {"message": text[:200]}, session_id=session_id)
        self.memory.store_message(session_id, LLMMessage(role=Role.USER, content=text))
        stored = self.memory.remember_from_message(session_id, text)
        if stored:
            log.debug("facts stored from message", count=stored)

        # TASK CONTINUATION: a follow-up fragment ("on my phone", "no, on the
        # laptop") MODIFIES the active task instead of starting a new one.
        # The follow-up text is still stored in the transcript above; the
        # execution goal + target come from persisted TaskState + the modifier.
        state = self.task_state.get(session_id) if self.task_state else None
        effective_goal = text
        if self._is_continuation(text, state):
            effective_goal = state["last_goal"]
            log.info("task continuation", follow_up=text[:60],
                     base_goal=effective_goal[:60], session=session_id)

        # TARGET RESOLUTION (before planning): decide the execution device.
        # For a continuation, capability + intent are judged on the COMBINED
        # text so "open youtube" + "on my phone" resolves to android.
        target = None
        if self.target_resolver is not None:
            probe = effective_goal if effective_goal == text else f"{effective_goal} {text}"
            capability = self._capability_for(probe)
            target = self.target_resolver.resolve(probe, capability, session_id)
            self.bus.emit(EventType.TARGET_RESOLVED,
                          target.to_dict(), session_id=session_id)
            log.info("target resolved", device=target.device, goal=effective_goal[:60],
                     session=session_id)

        try:
            plan, step = await self.planner.get_or_create(session_id, effective_goal)
        except Exception as e:  # noqa: BLE001 — planner failure classification
            info = classify(e, component="planner")
            info.suggestions = suggestions_for(info)
            log.warning("planner failure classified", failure_class=info.kind.value,
                        suggestions=info.suggestions, session=session_id)
            self.bus.emit(EventType.PLAN_FAILED,
                          {"failure_class": info.kind.value,
                           "detail": str(e)[:200],
                           "recovery_suggestions": info.suggestions},
                          session_id=session_id)
            return ("❌ Planning failed. " + " ".join(info.suggestions[:2]))
        if plan is None or step is None:
            # completed plan or nothing actionable
            if plan is not None:
                self.planner.mark_plan_completed(plan.id)
                return "✅ Your plan is already complete!\n\n" + self.planner.plan_summary(plan)
            return "I couldn't start a plan for that. Try rephrasing."

        outcome = await self.executor.run_step(
            session_id, plan, step, effective_goal,
            system_prompt_builder=lambda sid, pl: self._build_system_prompt(sid, pl),
            plan_id=plan.id,
            plan_completer=self.planner.mark_plan_completed,
            next_step_provider=self.planner.next_step,
            target_device=target.device if target else "windows",
        )
        # persist the ACTIVE TASK (structured, separate from the transcript)
        if self.task_state is not None:
            self.task_state.set(session_id, effective_goal,
                                target.device if target else "windows",
                                plan_id=plan.id, status=outcome.status)
        return self._outcome_to_text(outcome)

    def _is_continuation(self, text: str, state: dict | None) -> bool:
        """Is this message a follow-up that modifies the ACTIVE task?
        Conservative: only when a TaskState exists AND the message carries a
        target modifier ("on my phone"), a confirmation ("do it"), or a
        retry signal. Other fragments (e.g. "no wait, high priority") are NOT
        continuations — they fall to the LLM path, which has the full chat
        transcript in context and can resolve them conversationally."""
        if state is None or not state.get("last_goal"):
            return False
        low = " ".join(text.lower().split())
        if not low:
            return False
        return any(re.search(p, low) for p in _CONTINUATION_MARKERS)

    def _capability_for(self, text: str) -> str:
        """Infer the capability family from the goal (used by Target Resolution).
        The planner still reasons about capabilities — never about devices."""
        low = text.lower()
        if any(k in low for k in ("phone", "android", "mobile", "whatsapp",
                                  "notification", "youtube on my", "sms")):
            return "device.android"
        if any(k in low for k in ("browser", "chrome", "firefox", "edge", "web",
                                  "website", "http", "url")):
            return "workflow.browser"
        if any(k in low for k in ("remind", "todo", "task", "habit", "expense")):
            return "life.todos"
        if any(k in low for k in ("clipboard", "copy ", "paste")):
            return "clipboard"
        if any(k in low for k in ("folder", "file", "write", "read", "create a",
                                  "delete", "notes")):
            return "workflow.filesystem"
        return "generic"

    # ------------------------------------------------------------------ outcome → text
    def _outcome_to_text(self, outcome: StepOutcome) -> str:
        if outcome.status == StepStatus.CANCELLED.value:
            return "⛔ Task cancelled."
        if outcome.status == StepStatus.FAILED.value:
            return ("❌ Task failed after retries.\n" +
                    "\n".join(f"  • {e}" for e in outcome.errors[:4]) +
                    "\n\nSay 'resume' to retry, or rephrase.")
        if outcome.status == StepStatus.DONE.value:
            head = outcome.response or "Done."
            if outcome.observations:
                bad = [o for o in outcome.observations if "✗" in o]
                if bad:
                    head += "\n\n⚠️ Verification flags:\n" + "\n".join(bad[:3])
            if outcome.plan_finished:
                head += "\n\n✅ All plan steps complete."
            return head
        return outcome.response or "I made progress — ask to continue."

    # ------------------------------------------------------------------ resume
    async def resume(self, session_id: str) -> str:
        self.ensure_session(session_id)
        plan, step = self.planner.resume(session_id)
        if plan is None:
            return "No saved task to resume. Ask me something new!"
        self.bus.emit(EventType.SESSION_RESUMED,
                      {"plan": plan.id, "step": step.id if step else None},
                      session_id=session_id)
        if step is None:
            self.planner.mark_plan_completed(plan.id)
            return "✅ Your plan is already complete!\n\n" + self.planner.plan_summary(plan)
        return await self.handle_user_message(
            session_id, f"Continue the task: {step.title} (from saved plan {plan.id})")

    # ------------------------------------------------------------------ status
    def status(self, session_id: str) -> dict[str, Any]:
        history = self.memory.load_history(session_id)
        working = self.memory.load_working(session_id)
        plan = self.planner.get_active_plan(session_id)
        return {
            "session": session_id,
            "messages_in_history": len(history),
            "working": working,
            "active_plan": self.planner.plan_summary(plan) if plan else None,
            "devices": {d.name: d.health() for d in self.devices.all()},
            "tools_registered": len(self.registry),
        }
