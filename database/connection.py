"""AgentCore — database/connection.py
SQLite (WAL mode) via SQLAlchemy 2.0. One engine, one session factory.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def _set_pragmas(dbapi_conn, _record):  # noqa: ANN001
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


class Database:
    """SQLite (WAL) via SQLAlchemy. Schema is versioned with PRAGMA user_version;
    recovery/backup/integrity live in database/recovery.py."""

    SCHEMA_VERSION = 2   # bump when schema changes; migrations in database/migrations.py

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.path}", future=True)
        event.listen(self.engine, "connect", _set_pragmas)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self._fts_enabled = False

    # -- schema versioning ---------------------------------------------------
    def user_version(self) -> int:
        with self.engine.connect() as c:
            return c.exec_driver_sql("PRAGMA user_version").scalar() or 0

    def set_user_version(self, version: int) -> None:
        with self.engine.begin() as c:
            c.exec_driver_sql(f"PRAGMA user_version = {int(version)}")

    def create_all(self) -> None:
        from . import models  # noqa: F401  (registers models on Base)
        from database.recovery import ensure_columns
        Base.metadata.create_all(self.engine)
        ensure_columns(self)                 # additive column migration for old DBs
        self._setup_fts()
        if self.user_version() < self.SCHEMA_VERSION:
            self.set_user_version(self.SCHEMA_VERSION)

    def _setup_fts(self) -> None:
        """FTS5 virtual table over knowledge chunks (lexical search)."""
        try:
            with self.engine.begin() as conn:
                conn.exec_driver_sql(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts "
                    "USING fts5(content, tokenize='porter unicode61')")
                count = conn.exec_driver_sql(
                    "SELECT COUNT(*) FROM knowledge_fts").scalar()
                if count == 0:
                    conn.exec_driver_sql(
                        "INSERT OR IGNORE INTO knowledge_fts(rowid, content) "
                        "SELECT id, content FROM knowledge_chunks")
        except Exception:  # noqa: BLE001 — FTS optional; LIKE fallback covers it
            self._fts_enabled = False
        else:
            self._fts_enabled = True

    def drop_all(self) -> None:
        from . import models  # noqa: F401
        Base.metadata.drop_all(self.engine)

    def session(self):
        return self.session_factory()

    def close(self) -> None:
        self.engine.dispose()
