# AgentCore — Multi-Interface Runtime (architecture)

**One runtime. Every interface talks to it.** The backend (Planner, Executor,
Reasoner, Memory, Observer, Devices, Tools, Knowledge) is the single source of
truth and is **unchanged** by this work — we only reconnected the interfaces.

## 1. Architecture diagram

```
                AgentCore Runtime (one AgentApp)
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
   Desktop UI      Web Dashboard    Android Client
   (AgentCore.exe  (dev console,     (companion app,
    = launcher)     :8000)            /ws/android)
        │               │               │
        └───────────────┼───────────────┘
                        │
                 FastAPI Runtime API      (api/server.py + dashboard/app.py)
                        │
                 AgentApp / AgentCore     (core/app.py — composition root)
                        │
 Planner · Executor · Reasoner · Memory · Observer · Devices · Tools · Knowledge
```

- **Desktop UI** = `launcher.py` — starts/stops/monitors the runtime, opens the
  browser, system tray. It contains **no planner/executor logic**.
- **Web Dashboard** = `dashboard/app.py` + `dashboard/templates/dashboard.html`
  — thin presentation layer; talks **only** through the runtime API.
- **Android Client** = companion app → `/ws/android` + the same REST APIs.
- **One runtime**: every mode calls `dashboard.app.create_app()` → `AgentApp.create()`.

## 2. Startup sequence

### Development — `python main.py`
1. `main.py` → `_cmd_dev()` → `dashboard.app.run(reload=True)`
2. uvicorn (WatchFiles) spawns a worker importing `dashboard.app:create_app`
3. `AgentApp.create()` — initializes config → logging → SQLite → event bus →
   memory → LLM manager → tools → observers → planner → executor → devices
4. FastAPI starts; WebSocket endpoints (`/ws`, `/ws/android`) come up
5. Dashboard served at `http://localhost:8000` (hot reload ON)
6. Structured startup logs via structlog → `logs/agentcore.jsonl`

### Production — `AgentCore.exe` (or `python main.py --launcher`)
1. `launcher.run_launcher()` — prints launcher banner
2. `RuntimeServerThread` starts the **same** `dashboard.app.create_app()` runtime
3. Health-polled until ready
4. Opens the dashboard in the default browser (optional)
5. Runs in system tray (pystray) when supported; console fallback otherwise
6. Tray "Stop" (or Ctrl+C) → `server.should_exit = True` → graceful shutdown

## 3. Runtime API list (all interfaces use these)

| Purpose | Endpoint | Reused by |
|---|---|---|
| submit task | `POST /api/chat` | dashboard, CLI, future desktop/voice |
| stream execution | `POST /api/chat/stream` (SSE: `event` + `final`) | dashboard, future interfaces |
| resume saved task | `POST /api/resume` | dashboard, CLI |
| create plan | `POST /api/plan` | dashboard, CLI |
| planner state | `GET /api/planner` | dashboard |
| executor state | `GET /api/executor` | dashboard |
| current goal / step | `GET /api/status` (+ planner) | dashboard, CLI |
| memory summary | `GET /api/memory/facts` | dashboard |
| knowledge search / ingest | `GET /api/knowledge/search`, `POST /api/knowledge/ingest` | dashboard |
| observer events | `GET /api/observer` | dashboard |
| connected devices | `GET /api/devices`, `GET /api/devices/android/status` | dashboard |
| device pairing | `POST /api/devices/pair` | Android app |
| android link | `WS /ws/android` | Android companion |
| registered tools | `GET /api/tools` | dashboard |
| logs | `GET /api/logs` | dashboard |
| token usage | `GET /api/executions` (totals) | dashboard |
| runtime status | `GET /api/runtime` | dashboard, all |
| live events | `WS /ws` (event feed) | dashboard |
| providers / config | `POST /api/provider/check`, `POST /api/config/model` | dashboard, CLI |

## 4. Commands

```bash
# Development (primary entry) — dev console at http://localhost:8000, hot reload
python main.py
python main.py --no-reload        # disable hot reload
python main.py --dev              # explicit dev mode

# Production simulation (same runtime as AgentCore.exe)
python main.py --launcher [port]

# Build the Windows exe (on Windows) — AgentCore.exe = launcher
build.bat                          # or: python scripts/build.py

# Other entry points (same runtime)
python main.py chat                # CLI REPL
python main.py serve [port]        # dev console, no reload
python main.py selfcheck           # boot verification
```

## 5. Files

**Added**
- `launcher.py` — desktop launcher (runtime supervisor, browser, tray, graceful stop)
- `docs/ARCHITECTURE.md` — this document

**Modified**
- `dashboard/app.py` — hot-reload support; `create_app()` is the single runtime entry
- `dashboard/templates/dashboard.html` — added Observer tab, executor/runtime chips,
  token totals; existing styling/JS preserved
- `api/server.py` — added `/api/runtime`, `/api/executor`, `/api/observer`;
  `/api/executions` totals; SSE stream now emits live progress events
- `executor/executor.py` — optional event bus: emits TOOL_STARTED/TOOL_RESULT/STEP_* events
- `planning/direct.py` — deterministic fast-path: single-intent goals
  (time/weather/todo/clipboard/open-youtube) run their real tool WITHOUT the
  LLM; the Executor consults it before the LLM loop (complex goals excluded)
- `observer/manager.py` — recent-observation ring buffer
- `core/app.py` — wires bus into the Executor
- `main.py` — dev/launcher dispatch, `--dev`, `--launcher`, `--no-reload`
- `scripts/build.py`, `build.bat` — bundle `dashboard/templates`, tray/streaming hidden imports
- `pyproject.toml`, `requirements.txt` — `pystray`, `pillow`, `watchfiles`
- `README.md` — startup/API/commands documented
- `tests/test_api.py` — runtime/executor/observer endpoints + SSE progress checks

**Untouched (preserved):** backend architecture, HTML templates/styling, all other
API routes, tests, build scripts, config, the Android companion.

## 6. Single-runtime verification

Both modes build the app through the **same factory**:
- dev: `uvicorn "dashboard.app:create_app"` (reload worker)
- prod: `RuntimeServerThread` → `dashboard.app.create_app()`
- launcher source statically references `dashboard.app` (asserted in tests/dev)
- Live check: dev on :8000 and launcher on :9000 both report the identical runtime
  (`/api/runtime`: same provider, 24 tools, same devices).

**Guarantee:** any future interface (voice, desktop UI v2, Android, CLI) reuses
these APIs; no business logic lives in any frontend.
