"""AgentCore — planner/planner.py
Goal → persisted plan DAG. Continuity: an ACTIVE plan for a session is
reused; crash-resume marks RUNNING/WAITING_TOOL steps INTERRUPTED and
continues from the first actionable step.

The Planner depends on a `Reasoner` (NOT the LLMManager directly) — planning
can be done by the LLM, a local heuristic, or a human, without changing the
planner. Execution (the loop, retries, timeouts) is owned by the Executor;
the planner only manages plan/step state.
"""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.contracts import new_id
from database.models import Plan, PlanStep, WorkingMemory
from planner.steps import TERMINAL, StepStatus, can_transition
from reasoning.base import Reasoner

log = structlog.get_logger("agentcore.planner")

COMPLEXITY_THRESHOLD = 70


class Planner:
    def __init__(self, db_session_factory, reasoner: Reasoner) -> None:
        self.sf = db_session_factory
        self.reasoner = reasoner

    # ------------------------------------------------------------------ queries
    def get_active_plan(self, session_id: str) -> Plan | None:
        with self.sf() as s:
            return s.execute(select(Plan).options(selectinload(Plan.steps)).where(
                Plan.session_id == session_id, Plan.status == "ACTIVE")
                .order_by(Plan.created_at.desc())).scalars().first()

    def get_plan(self, plan_id: str) -> Plan | None:
        with self.sf() as s:
            return s.get(Plan, plan_id, options=[selectinload(Plan.steps)])

    def next_step(self, plan: Plan) -> PlanStep | None:
        with self.sf() as s:
            plan = s.get(Plan, plan.id)
            max_attempts = self._max_attempts()
            for step in plan.steps:
                if step.status == StepStatus.FAILED.value and step.attempts >= max_attempts:
                    step.status = StepStatus.BLOCKED.value
                    s.commit()
                    continue
                if step.status in (StepStatus.PENDING.value, StepStatus.CREATED.value,
                                   StepStatus.INTERRUPTED.value, StepStatus.FAILED.value):
                    return step
        return None

    def _max_attempts(self) -> int:
        try:
            from config.manager import get_config
            return get_config().get_int("planner.max_attempts", 3)
        except Exception:
            return 3

    # ------------------------------------------------------------------ creation
    async def get_or_create(self, session_id: str, goal: str) -> tuple[Plan, PlanStep | None]:
        existing = self.get_active_plan(session_id)
        if existing:
            return existing, self.next_step(existing)
        return await self.create_plan(session_id, goal)

    async def create_plan(self, session_id: str, goal: str) -> tuple[Plan, PlanStep | None]:
        plan_id = new_id("plan_")
        steps = await self._decompose(goal)
        with self.sf() as s:
            plan = Plan(id=plan_id, session_id=session_id, goal=goal, status="ACTIVE")
            s.add(plan)
            for i, title in enumerate(steps):
                s.add(PlanStep(id=new_id("step_"), plan_id=plan_id, title=title,
                               status=StepStatus.PENDING.value, order_idx=i))
            s.commit()
        plan = self.get_plan(plan_id)
        return plan, self.next_step(plan)

    # ------------------------------------------------------------------ decomposition
    _COMPLEX_MARKERS = re.compile(
        r"\b(then|next|and then|after that|finally|build|create|make|setup|install|"
        r"scaffold|plus|with|and)\b", re.I)

    async def _decompose(self, goal: str) -> list[str]:
        is_complex = (len(goal) > COMPLEXITY_THRESHOLD
                      or bool(self._COMPLEX_MARKERS.search(goal)))
        if not is_complex:
            return [goal]
        # try the reasoner (LLM → local heuristic → human, in that order)
        if self.reasoner is not None:
            dec = await self.reasoner.decompose(goal)
            if dec and dec.steps:
                return dec.steps
        # heuristic fallback
        parts = re.split(r"\s+(?:then|next|and then|after that|finally)\s+", goal, flags=re.I)
        return [p.strip() for p in parts if p.strip()] or [goal]

    # ------------------------------------------------------------------ transitions
    def set_step_status(self, step_id: str, status: StepStatus,
                        checkpoint: dict[str, Any] | None = None) -> None:
        with self.sf() as s:
            step = s.get(PlanStep, step_id)
            if step is None:
                return
            if can_transition(StepStatus(step.status), status):
                step.status = status.value
                step.attempts += 1 if status == StepStatus.RUNNING else 0
            if checkpoint is not None:
                step.checkpoint = json.dumps(checkpoint)
            if status in TERMINAL:
                from datetime import datetime, timezone
                step.finished_at = datetime.now(timezone.utc).isoformat()
            s.commit()

    def mark_plan_completed(self, plan_id: str) -> None:
        from datetime import datetime, timezone
        with self.sf() as s:
            plan = s.get(Plan, plan_id)
            if plan:
                plan.status = "COMPLETED"
                plan.completed_at = datetime.now(timezone.utc).isoformat()
                s.commit()

    # ------------------------------------------------------------------ resume
    def resume(self, session_id: str) -> tuple[Plan | None, PlanStep | None]:
        """After a crash: mark interrupted, return first actionable step."""
        plan = self.get_active_plan(session_id)
        if plan is None:
            return None, None
        with self.sf() as s:
            plan = s.get(Plan, plan.id)
            for step in plan.steps:
                if step.status in (StepStatus.RUNNING.value, StepStatus.WAITING_TOOL.value,
                                   StepStatus.OBSERVING.value, StepStatus.RETRYING.value,
                                   StepStatus.PLANNING.value):
                    step.status = StepStatus.INTERRUPTED.value
            s.commit()
        return plan, self.next_step(plan)

    def plan_summary(self, plan: Plan) -> str:
        with self.sf() as s:
            plan = s.get(Plan, plan.id)
            lines = [f"📋 Plan: {plan.goal} [{plan.status}]"]
            for st in plan.steps:
                mark = {"DONE": "✅", "RUNNING": "▶️", "WAITING_TOOL": "⏳",
                        "OBSERVING": "👁️", "RETRYING": "🔁", "BLOCKED": "🚧",
                        "FAILED": "❌", "CANCELLED": "⛔", "INTERRUPTED": "⚠️",
                        "PLANNING": "🧠"}.get(st.status, "⬜")
                lines.append(f"  {mark} {st.order_idx + 1}. {st.title} [{st.status}]")
            return "\n".join(lines)
