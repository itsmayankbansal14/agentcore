"""AgentCore — executor/executor.py
Dedicated execution engine. Owns:
  - step execution (the LLM ↔ tool loop for one plan step)
  - retries (attempts cap)
  - timeouts (per-step, per-run via ExecutionPolicy)
  - cancellation (asyncio CancelledError → step CANCELLED)
  - rollbacks (tool-level undo hooks; MVP: status rollback on failure)
  - parallel execution + dependency ordering (independent steps run together)
  - execution-history persistence (executions table)

The orchestrator coordinates (plan → execute → observe → next); it no longer
implements the loop. The Executor is the only place that runs tools.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from core.contracts import (ContextBundle, EventType, LLMMessage, Role,
                            ToolCall, ToolResult)
from database.connection import Database
from database.models import Execution, ToolExecution
from executor.policy import BudgetTracker, ExecutionPolicy
from llm.manager import LLMManager
from memory.manager import MemoryManager
from observer.manager import ObserverManager
from planner.steps import StepStatus
from tools.registry import ToolRegistry

log = structlog.get_logger("agentcore.executor")


@dataclass
class StepOutcome:
    step_id: str
    status: str
    response: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    budget: dict = field(default_factory=dict)
    duration_ms: int = 0
    plan_finished: bool = False


class Executor:
    def __init__(self, db: Database, llm: LLMManager, memory: MemoryManager,
                 registry: ToolRegistry, observers: ObserverManager,
                 policy: ExecutionPolicy | None = None, devices=None,
                 bus=None) -> None:
        self.db = db
        self.llm = llm
        self.memory = memory
        self.registry = registry
        self.observers = observers
        self.policy = policy or ExecutionPolicy()
        self.devices = devices
        self.bus = bus          # optional: publish tool/step events for the runtime API

    # ------------------------------------------------------------------ main entry
    async def run_step(self, session_id: str, plan, step, goal_text: str,
                       system_prompt_builder, plan_id: str | None = None,
                       plan_completer=None, next_step_provider=None) -> StepOutcome:
        """Execute one plan step through the agent loop with policy enforcement.
        system_prompt_builder(session_id, plan) -> str  (orchestrator provides it)
        plan_completer(plan_id) / next_step_provider(plan) -> callbacks for lifecycle
        """
        budget = BudgetTracker(self.policy)
        t0 = time.time()
        outcome = StepOutcome(step_id=step.id, status=StepStatus.RUNNING.value)
        self.memory.update_working(session_id, task=goal_text,
                                   plan_id=plan_id or (plan.id if plan else None),
                                   step_id=step.id, state={"phase": "executing"})

        violation = budget.check()
        if violation:
            return self._finish_failed(outcome, step, budget, t0, [violation])

        # history row
        exec_id = self._begin_execution(session_id, plan_id or (plan.id if plan else None),
                                        step.id, goal_text)

        attempts = 0
        while True:
            violation = budget.check()
            if violation:
                outcome.errors.append(violation)
                self._set_step(step, StepStatus.FAILED, budget, t0, outcome, exec_id)
                return outcome

            try:
                result = await asyncio.wait_for(
                    self._loop_once(session_id, plan, step, goal_text,
                                    system_prompt_builder, budget),
                    timeout=self.policy.step_timeout_s)
            except asyncio.CancelledError:
                self._set_step(step, StepStatus.CANCELLED, budget, t0, outcome, exec_id)
                outcome.status = StepStatus.CANCELLED.value
                log.info("step cancelled", step=step.id, session=session_id)
                raise
            except asyncio.TimeoutError:
                msg = f"step timeout after {self.policy.step_timeout_s}s"
                outcome.errors.append(msg)
                attempts += 1
                if attempts <= self.policy.max_retries:
                    self._set_step(step, StepStatus.RETRYING, budget, t0, outcome, exec_id)
                    log.warning("step timeout, retrying", step=step.id, attempt=attempts)
                    continue
                self._set_step(step, StepStatus.FAILED, budget, t0, outcome, exec_id)
                outcome.errors.append("retries exhausted after timeout")
                if self.bus is not None:
                    self.bus.emit(EventType.STEP_FAILED,
                                  {"step": step.id, "errors": outcome.errors},
                                  session_id=session_id)
                return outcome
            except Exception as e:  # noqa: BLE001
                outcome.errors.append(str(e))
                attempts += 1
                if attempts <= self.policy.max_retries:
                    self._set_step(step, StepStatus.RETRYING, budget, t0, outcome, exec_id)
                    log.warning("step error, retrying", step=step.id, attempt=attempts,
                                error=str(e)[:120])
                    continue
                self._set_step(step, StepStatus.FAILED, budget, t0, outcome, exec_id)
                if self.bus is not None:
                    self.bus.emit(EventType.STEP_FAILED,
                                  {"step": step.id, "errors": outcome.errors},
                                  session_id=session_id)
                return outcome

            # success
            outcome.response = result.get("response", "")
            outcome.tool_calls = result.get("tool_calls", [])
            outcome.observations = result.get("observations", [])
            outcome.budget = budget.summary()
            outcome.duration_ms = int((time.time() - t0) * 1000)
            self._set_step(step, StepStatus.DONE, budget, t0, outcome, exec_id)
            if self.bus is not None:
                self.bus.emit(EventType.STEP_COMPLETED,
                              {"step": step.id, "plan_id": plan_id or (plan.id if plan else None)},
                              session_id=session_id)

            # lifecycle: advance plan
            if plan is not None and plan_completer is not None:
                if next_step_provider is None or next_step_provider(plan) is None:
                    plan_completer(plan.id)
                    outcome.plan_finished = True
            return outcome

    # ------------------------------------------------------------------ the loop
    async def _loop_once(self, session_id, plan, step, goal_text,
                         system_prompt_builder, budget: BudgetTracker) -> dict:
        budget.steps_taken += 1
        ctx = await self.memory.load_context(session_id, user_message=goal_text)
        messages: list[LLMMessage] = [
            LLMMessage(role=Role.SYSTEM,
                       content=system_prompt_builder(session_id, plan))
        ] + ctx.history

        tool_calls_record: list[dict] = []
        observations: list[str] = []
        for _ in range(self.policy.max_steps):
            violation = budget.check()
            if violation:
                raise RuntimeError(violation)
            resp = await self.llm.chat(messages, tools=self._tools_for(step, goal_text),
                                       session_id=session_id,
                                       on_overflow=self._trim_context)
            if resp.usage:
                budget.record(resp.provider or "", resp.usage.prompt_tokens or 0,
                              resp.usage.completion_tokens or 0)
            self.memory.store_message(
                session_id, LLMMessage(role=Role.ASSISTANT, content=resp.content,
                                       tool_calls=resp.tool_calls),
                provider=resp.provider, model=resp.model)

            if not resp.tool_calls:
                return {"response": resp.content or "", "tool_calls": tool_calls_record,
                        "observations": observations}

            for tc in resp.tool_calls:
                result = await self._dispatch_tool(session_id, step.id, tc)
                tool_calls_record.append({"name": tc.name, "args": tc.arguments,
                                          "ok": result.ok, "error": result.error,
                                          "ms": result.duration_ms})
                # Observer: verify the tool's effect in the environment
                obs = self.observers.verify_after(
                    tc.name, tc.arguments,
                    result.data if isinstance(result.data, dict) else None)
                for o in obs:
                    observations.append(o.to_context())
                tool_msg = LLMMessage(role=Role.TOOL, content=str(result.data or result.error),
                                      tool_call_id=tc.id)
                self.memory.store_message(session_id, tool_msg)
                messages.append(LLMMessage(role=Role.ASSISTANT, content=resp.content,
                                           tool_calls=[tc]))
                messages.append(tool_msg)
                if observations:
                    messages.append(LLMMessage(
                        role=Role.SYSTEM,
                        content="Verification observations:\n" + "\n".join(observations[-3:])))

                # VERTICAL SLICE: real screen verification gate.
                # If the observer/vision verifier says the target did NOT open,
                # raise a retryable failure so the Executor's retry loop kicks in
                # (existing attempts/max_retries machinery — no new loop).
                failed_verif = [o for o in observations if "✗ verification failed" in o]
                if failed_verif and tc.name == "android_open_youtube":
                    self.memory.store_message(
                        session_id,
                        LLMMessage(role=Role.SYSTEM,
                                   content="VERIFICATION FAILED — the screen does not show YouTube. Retrying the open command."))
                    raise RuntimeError("screen verification failed: " + failed_verif[-1])

                # memory: record the completed device action as a long-term fact
                if tc.name == "android_open_youtube" and not failed_verif:
                    from datetime import datetime
                    self.memory.remember(session_id, "fact", "device.adb.last_action",
                                         f"opened youtube at {datetime.now().isoformat(timespec='seconds')}",
                                         source="verification")

        raise RuntimeError(f"iteration cap reached ({self.policy.max_steps})")

    # ------------------------------------------------------------------ tool dispatch
    async def _dispatch_tool(self, session_id: str, step_id: str | None,
                             tc: ToolCall) -> ToolResult:
        t0 = time.time()
        if self.bus is not None:
            self.bus.emit(EventType.TOOL_STARTED,
                          {"tool": tc.name, "args": tc.arguments},
                          session_id=session_id)
        with self.db.session() as s:
            row = ToolExecution(session_id=session_id, plan_step_id=step_id,
                                tool=tc.name, args=json.dumps(tc.arguments))
            s.add(row)
            s.commit()
            exec_id = row.id
        result = await self.registry.execute(tc.name, tc.arguments, ctx={
            "session_id": session_id, "confirm": True, "devices": self.devices})
        with self.db.session() as s:
            row = s.get(ToolExecution, exec_id)
            row.status = "ok" if result.ok else "error"
            row.duration_ms = result.duration_ms
            row.result = json.dumps(result.data, default=str) if result.ok else None
            row.error = result.error
            s.commit()
        if self.bus is not None:
            self.bus.emit(EventType.TOOL_RESULT,
                          {"tool": tc.name, "ok": result.ok,
                           "error": result.error, "ms": result.duration_ms},
                          session_id=session_id)
        return result

    # ------------------------------------------------------------------ history
    def _begin_execution(self, session_id, plan_id, step_id, goal) -> int:
        with self.db.session() as s:
            row = Execution(session_id=session_id, plan_id=plan_id, step_id=step_id,
                            goal=goal, status=StepStatus.RUNNING.value)
            s.add(row)
            s.commit()
            return row.id

    def _set_step(self, step, status: StepStatus, budget: BudgetTracker,
                  t0: float, outcome: StepOutcome, exec_id: int) -> None:
        outcome.status = status.value
        outcome.duration_ms = int((time.time() - t0) * 1000)
        outcome.budget = budget.summary()
        # mark step status (retries bump attempts)
        self._set_step_status(step, status)
        with self.db.session() as s:
            row = s.get(Execution, exec_id)
            if row:
                row.status = status.value
                row.duration_ms = outcome.duration_ms
                row.errors = json.dumps(outcome.errors)
                row.tokens_in = budget.tokens_in
                row.tokens_out = budget.tokens_out
                row.cost = budget.cost
                row.result = (outcome.response or "")[:2000]
                from datetime import datetime, timezone
                row.finished_at = datetime.now(timezone.utc).isoformat()
                s.commit()

    # Planner step status set (kept local to avoid circular import)
    def _set_step_status(self, step, status: StepStatus) -> None:
        from planner.steps import can_transition
        from database.models import PlanStep
        with self.db.session() as s:
            st = s.get(PlanStep, step.id)
            if st is None:
                return
            if can_transition(StepStatus(st.status), status):
                st.status = status.value
                st.attempts += 1 if status == StepStatus.RUNNING else 0
                if status in (StepStatus.DONE, StepStatus.FAILED, StepStatus.CANCELLED):
                    from datetime import datetime, timezone
                    st.finished_at = datetime.now(timezone.utc).isoformat()
                s.commit()

    # ------------------------------------------------------------------ helpers
    def _tools_for(self, step, goal_text: str):
        query = step.title if step else goal_text
        return self.registry.search(query, top_k=8)

    def _trim_context(self, session_id, messages):
        if len(messages) <= 6:
            return None
        summary = (messages[0].content or "")[:200] + " [older context trimmed]"
        return [LLMMessage(role=Role.SYSTEM, content=summary)] + messages[-4:]

    # ------------------------------------------------------------------ parallel
    async def run_plan(self, session_id, plan, goal_text, system_prompt_builder,
                       plan_completer=None) -> list[StepOutcome]:
        """Execute a plan's steps in dependency order; independent steps run in parallel."""
        from database.models import PlanStep
        with self.db.session() as s:
            steps = s.query(PlanStep).filter_by(plan_id=plan.id).order_by(
                PlanStep.order_idx).all()
        outcomes: dict[str, StepOutcome] = {}
        done = set()

        def _ready(steps) -> list:
            return [st for st in steps if st.id not in done and
                    (not st.parent_id or st.parent_id in done)]

        while len(done) < len(steps):
            batch = _ready(steps)
            if not batch:
                break  # dependency deadlock → stop
            results = await asyncio.gather(*[
                self.run_step(session_id, plan, st, goal_text, system_prompt_builder,
                              plan_completer=plan_completer)
                for st in batch])
            for st, out in zip(batch, results):
                outcomes[st.id] = out
                if out.status in (StepStatus.DONE.value, StepStatus.FAILED.value,
                                  StepStatus.CANCELLED.value):
                    done.add(st.id)
        return [outcomes[st.id] for st in steps if st.id in outcomes]
