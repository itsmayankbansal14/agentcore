"""AgentCore — database/migrations.py
Versioned schema migrations with rollback support. Each entry has an
`up` (apply) and `down` (rollback) statement list. The Database tracks
PRAGMA user_version; apply() runs only pending migrations.

Usage (maintenance):
  from database.migrations import migrate, rollback
  migrate(db)          # apply pending
  rollback(db, to=1)   # revert to a specific version
"""
from __future__ import annotations

import structlog

log = structlog.get_logger("agentcore.database.migrations")

# version -> {up: [...], down: [...]}  (additive/non-destructive preferred)
MIGRATIONS: dict[int, dict[str, list[str]]] = {
    2: {
        "up": [
            "ALTER TABLE tool_executions ADD COLUMN duration_ms INTEGER DEFAULT 0",
        ],
        "down": [],  # column drop not supported in SQLite; document instead
    },
}


def apply(db, target: int | None = None) -> list[int]:
    """Apply pending migrations up to `target` (default: latest)."""
    current = db.user_version()
    target = target or max(MIGRATIONS)
    applied = []
    for version in sorted(MIGRATIONS):
        if version <= current or version > target:
            continue
        stmts = MIGRATIONS[version].get("up", [])
        with db.engine.begin() as c:
            for stmt in stmts:
                c.exec_driver_sql(stmt)
        db.set_user_version(version)
        applied.append(version)
        log.info("migration applied", version=version)
    return applied


def rollback(db, to: int = 1) -> list[int]:
    """Roll back migrations above `to` using their `down` statements."""
    current = db.user_version()
    rolled = []
    for version in sorted(MIGRATIONS, reverse=True):
        if version <= to or version > current:
            continue
        stmts = MIGRATIONS[version].get("down", [])
        with db.engine.begin() as c:
            for stmt in stmts:
                c.exec_driver_sql(stmt)
        db.set_user_version(version - 1)
        rolled.append(version)
        log.warning("migration rolled back", version=version)
    return rolled
