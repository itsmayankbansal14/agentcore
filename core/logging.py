"""AgentCore — core/logging.py
Structured logging: JSONL to logs/agentcore.jsonl + human console, plus a
separate audit log for tool/device executions.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import structlog


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class JSONLinesSink:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __call__(self, logger, method_name, event_dict):  # noqa: ANN001
        record = {"ts": _ts(), "level": method_name, "event": event_dict.pop("event", ""), **event_dict}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        return event_dict


def setup_logging(log_dir: Path, level: int = logging.INFO) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    json_path = log_dir / "agentcore.jsonl"

    try:
        from structlog.dev import ConsoleRenderer
    except ImportError:  # older structlog
        ConsoleRenderer = structlog.processors.ConsoleRenderer

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            JSONLinesSink(json_path),
            ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # route stdlib logging into structlog for third-party libs
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stderr)

    # quiet noisy HTTP/SDK loggers (httpx prints every request at INFO)
    for noisy in ("httpx", "httpcore", "openai", "urllib3", "anthropic", "google"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class AuditLog:
    """Immutable audit trail of tool/device executions (also mirrored to DB)."""

    def __init__(self, log_dir: Path) -> None:
        self.path = log_dir / "audit.jsonl"

    def record(self, action: str, target: str, actor: str = "agent", detail: dict | None = None) -> None:
        entry = {"ts": _ts(), "actor": actor, "action": action, "target": target, "detail": detail or {}}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")


_log: AuditLog | None = None


def get_audit() -> AuditLog:
    global _log
    if _log is None:
        _log = AuditLog(Path("./logs"))
    return _log


def bind_audit(log_dir: Path) -> None:
    global _log
    _log = AuditLog(log_dir)
