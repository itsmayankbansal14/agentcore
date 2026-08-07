#!/usr/bin/env python3
"""AgentCore — scripts/migrate_jarvis.py
Migrate the JARVIS prototype's JSON data files into AgentCore SQLite.

Usage:
  python scripts/migrate_jarvis.py [--jarvis /path/to/jarvis] [--dry-run]

Migrates: data/todos.json → todos, data/habits.json → habits,
          data/expenses.json → expenses
Idempotent: refuses to double-import if tables already contain rows
(use --force to wipe and re-import).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.app import AgentApp
from database.models import Expense, Habit, Todo


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def migrate(jarvis_dir: Path, db, dry_run: bool, force: bool) -> dict:
    data_dir = jarvis_dir / "data"
    report = {"todos": 0, "habits": 0, "expenses": 0, "skipped": False}

    with db.session() as s:
        if s.query(Todo).count() > 0 and not force:
            report["skipped"] = True
            print("⚠️  todos table already has rows — use --force to re-import.")
            return report

        # ---- todos ----
        for t in _load_json(data_dir / "todos.json", []):
            if not isinstance(t, dict) or not t.get("task"):
                continue
            row = Todo(task=str(t["task"])[:500],
                       priority=str(t.get("priority", "medium")),
                       category=str(t.get("category", "general")),
                       done=bool(t.get("done", False)),
                       created_at=str(t.get("created", "")) or None)
            if not dry_run:
                s.add(row)
            report["todos"] += 1

        # ---- habits ----
        for h in _load_json(data_dir / "habits.json", []):
            if not isinstance(h, dict) or not h.get("name"):
                continue
            history = h.get("history", [])
            row = Habit(name=str(h["name"])[:200],
                        frequency=str(h.get("frequency", h.get("freq", "daily"))),
                        streak=int(h.get("streak", 0)),
                        history=json.dumps(history if isinstance(history, list) else []))
            if not dry_run:
                s.add(row)
            report["habits"] += 1

        # ---- expenses ----
        for e in _load_json(data_dir / "expenses.json", []):
            if not isinstance(e, dict) or e.get("amount") is None:
                continue
            try:
                amount = float(e["amount"])
            except (TypeError, ValueError):
                continue
            row = Expense(amount=amount,
                          category=str(e.get("category", "general")),
                          note=str(e.get("note", ""))[:300],
                          date=str(e.get("date", "")) or None)
            if not dry_run:
                s.add(row)
            report["expenses"] += 1

        if not dry_run:
            s.commit()
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Migrate JARVIS JSON data into AgentCore SQLite")
    ap.add_argument("--jarvis", default="/home/user/jarvis", help="path to the jarvis project")
    ap.add_argument("--dry-run", action="store_true", help="count only, don't write")
    ap.add_argument("--force", action="store_true", help="wipe existing rows and re-import")
    args = ap.parse_args()

    jarvis_dir = Path(args.jarvis).resolve()
    if not (jarvis_dir / "data").is_dir():
        print(f"❌ no data/ dir under {jarvis_dir}")
        sys.exit(1)

    app = AgentApp.create()
    print(f"🧪 migrating {jarvis_dir}/data → {app.db.path}"
          + ("   [DRY RUN]" if args.dry_run else ""))

    if args.force:
        with app.db.session() as s:
            s.query(Expense).delete(); s.query(Habit).delete(); s.query(Todo).delete()
            s.commit()
        print("🗑️  cleared existing rows")

    report = migrate(jarvis_dir, app.db, args.dry_run, args.force)
    print(f"✅ todos    : {report['todos']}")
    print(f"✅ habits   : {report['habits']}")
    print(f"✅ expenses : {report['expenses']}")
    if report["skipped"]:
        print("(skipped — tables non-empty; use --force to overwrite)")


if __name__ == "__main__":
    main()
