#!/usr/bin/env python3
"""AgentCore — main.py (CLI entry point)

Usage:
  python main.py chat                 interactive REPL
  python main.py say "goal text"      one-shot
  python main.py plan "goal"          create/show plan
  python main.py resume               continue saved task
  python main.py status               session + device + plan status
  python main.py whoami               print provider/config summary
  python main.py ingest <file|dir>    index files into the knowledge base
  python main.py search <query>       search indexed knowledge
  python main.py facts                show long-term memory facts
  python main.py                      start the dev console (dashboard) at http://localhost:8000
  python main.py chat                 interactive REPL
  python main.py serve [port]         start the dev console (default 8000)
  python main.py selfcheck            verify the app boots (used by build smoke test)
  python main.py version              print version
"""
from __future__ import annotations

import asyncio
import sys

from core.app import AgentApp


def _app():
    return AgentApp.create()


def cmd_whoami(app: AgentApp) -> None:
    cfg = app.config
    print(f"AgentCore · {cfg.get_str('app.name', 'AgentCore')}")
    print(f"data dir : {cfg.data_dir}")
    print(f"providers: {cfg.get_list('llm.provider_priority', [])}")
    for key in app.llm.router.keys:
        print(f"  - {key.provider:10s} model={key.model:30s} failures={key.consecutive_failures}"
              f" cooldown={'yes' if key.cooldown_until > 0 else 'no'}")
    print(f"tools    : {len(app.registry)} registered")
    print(f"devices  : {[(d.name, d.health()) for d in app.devices.all()]}")


def cmd_status(app: AgentApp, session_id: str) -> None:
    st = app.orchestrator.status(session_id)
    print(f"session    : {st['session']}")
    print(f"messages   : {st['messages_in_history']}")
    print(f"working    : {st['working'].get('current_task') or '(none)'}")
    if st["active_plan"]:
        print(st["active_plan"])
    print(f"devices    : {st['devices']}")
    print(f"tools      : {st['tools_registered']}")


def cmd_plan(app: AgentApp, session_id: str, goal: str) -> None:
    # explicit "plan X" always starts a fresh plan (chat keeps continuation semantics)
    app.orchestrator.ensure_session(session_id)
    plan, step = asyncio.run(app.planner.create_plan(session_id, goal))
    print(app.planner.plan_summary(plan))
    if step:
        print(f"\n▶ next step: {step.title}")


def cmd_resume(app: AgentApp, session_id: str) -> None:
    print(asyncio.run(app.orchestrator.resume(session_id)))


def cmd_ingest(app: AgentApp, path: str) -> None:
    from pathlib import Path
    p = Path(path).resolve()
    if p.is_dir():
        result = asyncio.run(app.memory.add_knowledge_dir(str(p)))
        print(f"📚 indexed dir: {result}")
    else:
        result = asyncio.run(app.memory.add_knowledge(str(p)))
        print(f"📚 {result}")
    print(f"   vector store: {len(app.memory.vector)} chunks embedded")


def cmd_search(app: AgentApp, query: str, top_k: int = 5) -> None:
    hits = asyncio.run(app.memory.search_knowledge(query, top_k=top_k))
    if not hits:
        print("(no knowledge hits)")
        return
    for h in hits:
        print("•", h[:160])


def cmd_facts(app: AgentApp, session_id: str) -> None:
    facts = app.memory.recall(session_id, top_k=50)
    if not facts:
        print("(no long-term facts yet)")
        return
    for f in facts:
        print("•", f)


def repl(app: AgentApp, session_id: str) -> None:
    print("AgentCore REPL — type your goal, 'resume', 'status', or 'quit'.\n")
    while True:
        try:
            line = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break
        if not line:
            continue
        low = line.lower()
        if low in ("quit", "exit", "bye", "q"):
            print("bye")
            break
        if low == "resume":
            print(cmd_resume(app, session_id))
            continue
        if low == "status":
            cmd_status(app, session_id)
            continue
        if low.startswith("plan "):
            cmd_plan(app, session_id, line[5:])
            continue
        result = asyncio.run(app.orchestrator.handle_user_message(session_id, line))
        print(f"\n🤖 {result}")


def _cmd_serve(app, port: int | None = None) -> None:
    """Boot the dev console (thin dashboard) — primary entry point."""
    from dashboard.app import run as run_dashboard
    run_dashboard(app, port=port)


def main() -> None:
    args = sys.argv[1:]
    session_id = "demo"
    app = _app()

    if not args:
        # PRIMARY ENTRY: `python main.py` → dev console at localhost:8000
        _cmd_serve(app)
        return
    if args[0] == "chat":
        repl(app, session_id)
    elif args[0] == "say":
        print(asyncio.run(app.orchestrator.handle_user_message(session_id, " ".join(args[1:]))))
    elif args[0] == "plan":
        cmd_plan(app, session_id, " ".join(args[1:]))
    elif args[0] == "resume":
        cmd_resume(app, session_id)
    elif args[0] == "status":
        cmd_status(app, session_id)
    elif args[0] == "whoami":
        cmd_whoami(app)
    elif args[0] == "ingest":
        if len(args) < 2:
            print("usage: python main.py ingest <file-or-dir>")
        else:
            cmd_ingest(app, args[1])
    elif args[0] == "search":
        if len(args) < 2:
            print("usage: python main.py search <query>")
        else:
            cmd_search(app, " ".join(args[1:]))
    elif args[0] == "facts":
        cmd_facts(app, session_id)
    elif args[0] in ("selfcheck", "--selfcheck"):
        sys.exit(cmd_selfcheck(app))
    elif args[0] in ("version", "--version", "-v"):
        try:
            import tomllib
            with open("pyproject.toml", "rb") as f:
                print("AgentCore", tomllib.load(f)["project"]["version"])
        except Exception:
            print("AgentCore 0.1.0")
    elif args[0] == "serve":
        port = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
        _cmd_serve(app, port)
    else:
        print(__doc__)


def cmd_selfcheck(app) -> int:
    """Boot verification for the packaged executable (build smoke test).
    Exits 0 only if the app boots, tools register, and the DB opens."""
    try:
        if len(app.registry) < 5:
            print(f"SELFCHECK FAIL — only {len(app.registry)} tools registered")
            return 1
        with app.db.engine.connect() as c:
            c.exec_driver_sql("SELECT 1")
        print(f"SELFCHECK OK — tools={len(app.registry)} db=ok "
              f"devices={[d.name for d in app.devices.all()]}")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"SELFCHECK FAIL — {e}")
        return 1


if __name__ == "__main__":
    main()
