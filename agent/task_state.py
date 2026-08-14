"""AgentCore — agent/task_state.py
Persistent, structured Task State — the user's active task.

This is deliberately SEPARATE from conversation history: the Executor never
reconstructs execution state from the chat transcript. The orchestrator uses
TaskState only as a continuity anchor so a follow-up like "on my phone" after
"open youtube" modifies the active task instead of starting an unrelated one.
"""
from __future__ import annotations

import structlog

from database.connection import Database
from database.models import TaskState

log = structlog.get_logger("agentcore.task_state")


class TaskStateStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, session_id: str) -> dict | None:
        with self.db.session() as s:
            row = s.get(TaskState, session_id)
            if row is None:
                return None
            return {"session_id": row.session_id, "last_goal": row.last_goal,
                    "last_target": row.last_target, "last_plan_id": row.last_plan_id,
                    "last_status": row.last_status, "updated_at": row.updated_at}

    def set(self, session_id: str, goal: str, target: str,
            plan_id: str = "", status: str = "") -> None:
        with self.db.session() as s:
            row = s.get(TaskState, session_id)
            if row is None:
                row = TaskState(session_id=session_id)
                s.add(row)
            row.last_goal = goal
            row.last_target = target
            row.last_plan_id = plan_id or row.last_plan_id
            row.last_status = status or row.last_status
            from database.models import now
            row.updated_at = now()
            s.commit()
        log.debug("task state set", session=session_id, goal=goal[:60],
                  target=target, plan=plan_id)

    def clear(self, session_id: str) -> None:
        with self.db.session() as s:
            row = s.get(TaskState, session_id)
            if row is not None:
                s.delete(row)
                s.commit()
