"""Integration: Database recovery (integrity, backups, schema migration, KV).

Real: SQLite via the runtime's Database; integrity_check on a live DB;
online backup via VACUUM INTO; additive column migration (ensure_columns);
schema version tracking (PRAGMA user_version); the migrations module applies
the pending migration.
"""
import pytest

from database import recovery
from database.migrations import apply


@pytest.mark.integration
def test_integrity_and_backup(app):
    problems = recovery.integrity_check(app.db)
    assert problems == []
    bk = recovery.backup(app.db)
    assert bk.exists() and bk.stat().st_size > 0
    assert recovery.integrity_check(app.db) == []


@pytest.mark.integration
def test_schema_version_and_migration(app):
    assert app.db.user_version() >= 2
    applied = apply(app.db)
    assert isinstance(applied, list)
    # additive columns exist on the live tool history table
    with app.db.engine.connect() as c:
        cols = {r[1] for r in c.exec_driver_sql("PRAGMA table_info(tool_executions)").all()}
    assert {"retries", "failure_class", "rollback", "recovery_suggestions"} <= cols


@pytest.mark.integration
def test_recovery_restores_data(app, session, mock_llm, run_sync):
    # write data, then verify it survives a fresh Database handle on the same file
    mock_llm.enqueue('[TOOL time_now {}]', 'ok')
    plan, step = run_sync(app.planner.create_plan(session, "what time is it?"))
    run_sync(app.executor.run_step(
        session, plan, step, "what time is it?",
        system_prompt_builder=lambda sid, pl: "sys",
        plan_id=plan.id, plan_completer=app.planner.mark_plan_completed,
        next_step_provider=app.planner.next_step))
    path = app.db.path
    app.db.close()
    from database.connection import Database
    db2 = Database(path)
    db2.create_all()
    with db2.session() as s:
        from database.models import Execution
        n = s.query(Execution).filter_by(session_id=session).count()
    assert n >= 1  # execution history survived re-open
    db2.close()
