"""AgentCore — tools/local/life.py
LifeOS tools migrated from the JARVIS prototype into the tool registry,
backed by SQLite (no more JSON files). Todos, habits, expenses.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from core.contracts import ToolResult
from database.connection import Database
from database.models import Expense, Habit, Todo
from tools.base import Tool


class TodoAddTool(Tool):
    name = "todo_add"
    description = "Add a todo task."
    parameters = {"type": "object",
                  "properties": {"task": {"type": "string"},
                                 "priority": {"type": "string", "enum": ["low", "medium", "high"]}},
                  "required": ["task"]}
    capability = "life.todos"
    idempotent = False

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        with self.db.session() as s:
            t = Todo(task=params["task"], priority=params.get("priority", "medium"))
            s.add(t)
            s.commit()
            return ToolResult(ok=True, data={"id": t.id, "task": t.task, "priority": t.priority})


class TodoListTool(Tool):
    name = "todo_list"
    description = "List todos (optionally only pending)."
    parameters = {"type": "object",
                  "properties": {"pending_only": {"type": "boolean", "default": True}},
                  "required": []}
    capability = "life.todos"
    idempotent = True

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        pending_only = params.get("pending_only", True)
        with self.db.session() as s:
            q = s.query(Todo)
            if pending_only:
                q = q.filter(Todo.done.is_(False))
            rows = q.order_by(Todo.id).all()
            return ToolResult(ok=True, data={
                "todos": [{"id": r.id, "task": r.task, "priority": r.priority,
                           "done": r.done} for r in rows], "count": len(rows)})


class TodoDoneTool(Tool):
    name = "todo_done"
    description = "Mark a todo as done by id."
    parameters = {"type": "object", "properties": {"id": {"type": "integer"}},
                  "required": ["id"]}
    capability = "life.todos"
    idempotent = False

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        with self.db.session() as s:
            t = s.get(Todo, int(params["id"]))
            if t is None:
                return ToolResult(ok=False, error=f"no todo #{params['id']}")
            t.done = True
            s.commit()
            return ToolResult(ok=True, data={"id": t.id, "task": t.task})


class HabitCheckTool(Tool):
    name = "habit_check"
    description = "Check off a habit for today (name or id); increments streak."
    parameters = {"type": "object", "properties": {"name": {"type": "string"}},
                  "required": ["name"]}
    capability = "life.habits"
    idempotent = False

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        today = date.today().isoformat()
        with self.db.session() as s:
            h = s.query(Habit).filter(Habit.name.ilike(params["name"])).first()
            if h is None:
                return ToolResult(ok=False, error=f"no habit: {params['name']}")
            history = json.loads(h.history or "[]")
            if today in history:
                return ToolResult(ok=True, data={"name": h.name, "streak": h.streak,
                                                 "already": True})
            history.append(today)
            h.history = json.dumps(history)
            h.streak += 1
            s.commit()
            return ToolResult(ok=True, data={"name": h.name, "streak": h.streak,
                                             "already": False})


class HabitAddTool(Tool):
    name = "habit_add"
    description = "Add a new habit."
    parameters = {"type": "object",
                  "properties": {"name": {"type": "string"},
                                 "frequency": {"type": "string", "default": "daily"}},
                  "required": ["name"]}
    capability = "life.habits"
    idempotent = False

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        with self.db.session() as s:
            existing = s.query(Habit).filter(Habit.name.ilike(params["name"])).first()
            if existing:
                return ToolResult(ok=False, error=f"habit already exists: {existing.name}")
            h = Habit(name=params["name"], frequency=params.get("frequency", "daily"))
            s.add(h)
            s.commit()
            return ToolResult(ok=True, data={"id": h.id, "name": h.name})


class ExpenseAddTool(Tool):
    name = "expense_add"
    description = "Add an expense (amount, category, note)."
    parameters = {"type": "object",
                  "properties": {"amount": {"type": "number"},
                                 "category": {"type": "string", "default": "general"},
                                 "note": {"type": "string", "default": ""}},
                  "required": ["amount"]}
    capability = "life.expenses"
    idempotent = False

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        with self.db.session() as s:
            e = Expense(amount=float(params["amount"]),
                        category=params.get("category", "general"),
                        note=params.get("note", ""))
            s.add(e)
            s.commit()
            return ToolResult(ok=True, data={"id": e.id, "amount": e.amount,
                                             "category": e.category})


class ExpenseSummaryTool(Tool):
    name = "expense_summary"
    description = "Total expenses + breakdown by category."
    parameters = {"type": "object", "properties": {}}
    capability = "life.expenses"
    idempotent = True

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict[str, Any], ctx: dict[str, Any]) -> ToolResult:
        with self.db.session() as s:
            rows = s.query(Expense).all()
            total = sum(r.amount for r in rows)
            by_cat: dict[str, float] = {}
            for r in rows:
                by_cat[r.category] = by_cat.get(r.category, 0.0) + r.amount
            return ToolResult(ok=True, data={"total": round(total, 2),
                                             "by_category": by_cat, "count": len(rows)})


def register_all(registry, db: Database) -> None:
    for tool in (TodoAddTool(db), TodoListTool(db), TodoDoneTool(db),
                 HabitAddTool(db), HabitCheckTool(db),
                 ExpenseAddTool(db), ExpenseSummaryTool(db)):
        registry.register(tool)
