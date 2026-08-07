"""AgentCore — database/recovery.py
SQLite recovery strategy (Phase 2):
  - integrity_check on open
  - automatic backups (VACUUM INTO) before schema changes + periodic
  - recovery mode: rebuild from backup if corrupt
  - additive column migration for old DB files (ensure_columns)
Rollback of destructive migrations is handled by migrations.py (version list).
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger("agentcore.database.recovery")

# additive columns applied to existing DB files when missing
_ADDITIVE_COLUMNS: list[tuple[str, str, str]] = [
    ("tool_executions", "duration_ms", "INTEGER DEFAULT 0"),
]


def ensure_columns(db) -> None:
    """Add missing columns to existing tables (non-destructive forward migration)."""
    try:
        with db.engine.connect() as c:
            for table, column, ddl in _ADDITIVE_COLUMNS:
                cols = {r[1] for r in c.exec_driver_sql(f"PRAGMA table_info({table})").all()}
                if column not in cols:
                    c.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    except Exception as e:  # noqa: BLE001
        log.warning("ensure_columns failed", error=str(e))


def integrity_check(db) -> list[str]:
    """Run PRAGMA integrity_check; returns list of problems (empty = healthy)."""
    try:
        with db.engine.connect() as c:
            rows = c.exec_driver_sql("PRAGMA integrity_check").all()
            return [str(r[0]) for r in rows if str(r[0]) != "ok"]
    except Exception as e:  # noqa: BLE001
        return [f"integrity check failed: {e}"]


def backup(db, dest: Path | None = None) -> Path:
    """Consistent online backup via VACUUM INTO."""
    dest = dest or db.path.with_name(f"{db.path.stem}.backup-{datetime.now():%Y%m%d-%H%M%S}.db")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with db.engine.connect() as c:
        c.exec_driver_sql(f"VACUUM INTO '{dest}'")
    log.info("db backup created", path=str(dest))
    return dest


def recover(db, backup_dir: Path | None = None) -> bool:
    """Recovery mode: try to repair a corrupt DB; restore newest backup if needed."""
    problems = integrity_check(db)
    if not problems:
        return True  # healthy already
    log.warning("integrity problems detected", problems=problems[:5])

    # attempt repair via full VACUUM (rebuilds file, drops corrupt pages)
    try:
        with db.engine.connect() as c:
            c.exec_driver_sql("VACUUM")
        if not integrity_check(db):
            log.info("db repaired via VACUUM")
            return True
    except Exception as e:  # noqa: BLE001
        log.warning("vacuum repair failed", error=str(e))

    # restore newest backup
    if backup_dir is not None:
        backups = sorted(backup_dir.glob("*.db")) if backup_dir.exists() else []
        if backups:
            newest = backups[-1]
            try:
                db.engine.dispose()
                shutil.copy2(newest, db.path)
                log.warning("restored db from backup", path=str(newest))
                return True
            except Exception as e:  # noqa: BLE001
                log.error("backup restore failed", error=str(e))
    return False
