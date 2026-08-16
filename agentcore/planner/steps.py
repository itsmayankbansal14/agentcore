"""AgentCore — planner/steps.py
Task lifecycle state machine (per review):
  Created → Planning → Executing → Waiting → Observing → Retrying
       ↘ Completed · Failed · Cancelled

Mapped to storage statuses: PENDING≈Created, PLANNING, RUNNING≈Executing,
WAITING_TOOL≈Waiting, OBSERVING, RETRYING, DONE≈Completed, FAILED,
CANCELLED. BLOCKED is the human-gate state (needs user input to resume).
"""
from __future__ import annotations

from enum import Enum


class StepStatus(str, Enum):
    CREATED = "CREATED"            # created but not yet planned
    PLANNING = "PLANNING"          # being decomposed
    PENDING = "PENDING"            # queued, ready to execute (alias of Created)
    RUNNING = "RUNNING"            # executing
    WAITING_TOOL = "WAITING_TOOL"  # waiting on a tool/device result
    OBSERVING = "OBSERVING"        # verifying outcome in the environment
    RETRYING = "RETRYING"          # retrying after transient failure
    BLOCKED = "BLOCKED"            # needs human input/permission
    DONE = "DONE"                  # completed
    FAILED = "FAILED"              # failed after retries
    CANCELLED = "CANCELLED"        # cancelled (user/timeout/limit)
    INTERRUPTED = "INTERRUPTED"    # crash mid-execution; resumable


TERMINAL = {StepStatus.DONE, StepStatus.FAILED, StepStatus.CANCELLED}

# allowed transitions (kept strict so state bugs surface early)
TRANSITIONS: dict[StepStatus, set[StepStatus]] = {
    StepStatus.CREATED: {StepStatus.PLANNING, StepStatus.PENDING, StepStatus.CANCELLED},
    StepStatus.PLANNING: {StepStatus.PENDING, StepStatus.BLOCKED, StepStatus.CANCELLED},
    StepStatus.PENDING: {StepStatus.RUNNING, StepStatus.BLOCKED, StepStatus.CANCELLED},
    StepStatus.RUNNING: {StepStatus.WAITING_TOOL, StepStatus.OBSERVING,
                         StepStatus.RETRYING, StepStatus.DONE, StepStatus.FAILED,
                         StepStatus.CANCELLED},
    StepStatus.WAITING_TOOL: {StepStatus.RUNNING, StepStatus.OBSERVING,
                              StepStatus.FAILED, StepStatus.CANCELLED},
    StepStatus.OBSERVING: {StepStatus.RUNNING, StepStatus.RETRYING,
                           StepStatus.DONE, StepStatus.FAILED, StepStatus.CANCELLED},
    StepStatus.RETRYING: {StepStatus.RUNNING, StepStatus.FAILED, StepStatus.CANCELLED},
    StepStatus.BLOCKED: {StepStatus.PENDING, StepStatus.RUNNING, StepStatus.CANCELLED},
    StepStatus.FAILED: {StepStatus.RUNNING, StepStatus.PENDING},   # explicit re-run only
    StepStatus.INTERRUPTED: {StepStatus.RUNNING, StepStatus.PENDING},
    StepStatus.DONE: set(),
    StepStatus.CANCELLED: set(),
}


def can_transition(current: StepStatus, next_: StepStatus) -> bool:
    return next_ in TRANSITIONS.get(current, set())
