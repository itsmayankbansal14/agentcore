"""AgentCore — tools/storage/todo_storage.py
TodoStorage — capability interface for todo persistence.

The Planner/Executor/tools depend on this interface, NOT on a filesystem or
database. Implementations are interchangeable:
  - SQLiteTodoStorage (default, backed by the runtime Database)
  - a future cloud/JSON backend can be swapped in without touching the planner

Self-healing: if the storage is missing/not-initialized, `ensure_initialized()`
creates it, then the caller retries the original operation — and the
integration test verifies exactly that flow.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TodoStorage(ABC):
    """Capability interface for todos."""

    @abstractmethod
    def is_initialized(self) -> bool: ...

    @abstractmethod
    def initialize(self) -> None:
        """Create the storage if it does not exist (self-healing)."""
        ...

    @abstractmethod
    def add(self, task: str, priority: str = "medium",
            category: str = "general") -> int: ...

    @abstractmethod
    def list(self, pending_only: bool = True) -> list[dict]: ...

    @abstractmethod
    def mark_done(self, todo_id: int) -> dict | None: ...

    @abstractmethod
    def stats(self) -> dict: ...

    def ensure_initialized(self) -> None:
        """Self-healing: initialize if missing, then the caller retries."""
        if not self.is_initialized():
            self.initialize()


class SQLiteTodoStorage(TodoStorage):
    """SQLite-backed implementation. Filesystem/DB is an internal detail —
    callers only see the capability interface."""

    def __init__(self, db) -> None:
        self.db = db

    def _table_exists(self) -> bool:
        with self.db.engine.connect() as c:
            return c.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='todos'"
            ).scalar() is not None

    def is_initialized(self) -> bool:
        return self._table_exists()

    def initialize(self) -> None:
        # create_all is idempotent and creates the todos table if missing
        from database.connection import Base
        from database import models  # noqa: F401  (register models)
        Base.metadata.create_all(self.db.engine)

    def add(self, task: str, priority: str = "medium",
            category: str = "general") -> int:
        from database.models import Todo
        with self.db.session() as s:
            t = Todo(task=task, priority=priority, category=category)
            s.add(t)
            s.commit()
            return t.id

    def list(self, pending_only: bool = True) -> list[dict]:
        from database.models import Todo
        with self.db.session() as s:
            q = s.query(Todo)
            if pending_only:
                q = q.filter(Todo.done.is_(False))
            return [{"id": r.id, "task": r.task, "priority": r.priority,
                     "category": r.category, "done": r.done}
                    for r in q.order_by(Todo.id).all()]

    def mark_done(self, todo_id: int) -> dict | None:
        from database.models import Todo
        with self.db.session() as s:
            t = s.get(Todo, todo_id)
            if t is None:
                return None
            t.done = True
            s.commit()
            return {"id": t.id, "task": t.task}

    def stats(self) -> dict:
        todos = self.list(pending_only=False)
        return {"todos_pending": sum(1 for t in todos if not t["done"]),
                "todos_total": len(todos)}


class TodoStorageProvider:
    """Resolves the storage instance and guarantees self-healing init.
    The Executor injects this into tool ctx; tools call
    `provider.storage()` which auto-initializes on first use."""

    def __init__(self, storage: TodoStorage) -> None:
        self._storage = storage
        self.initialized = False

    def storage(self) -> TodoStorage:
        if not self.initialized:
            self._storage.ensure_initialized()
            self.initialized = True
        return self._storage
