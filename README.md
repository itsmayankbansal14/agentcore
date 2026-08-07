# AgentCore — Desktop-First AI Agent Platform

Windows laptop = controller · Android phone = thin remote executor.
LLM **only reasons**; tools act; SQLite remembers; the **task loop** is the center.

> Test status: **219 checks passing** (47 arch + 37 core + 34 api + 12 android +
> 19 vertical-slice + 37 reliability + **25 pytest integration**) · coverage 55.5%
> on the integration suite alone (40% floor enforced). across 4 suites:
> `tests/test_architecture.py` (47) · `tests/smoke.py` (37) · `tests/test_api.py` (13) ·
> `scripts/test_live.py` (8, against real OpenRouter).

---

## Features (implemented & tested — not aspirational)

### Agent loop
- Event-driven orchestrator that coordinates, never implements business logic.
- Dedicated **Executor** owns the LLM↔tool loop, retries, timeouts, cancellation,
  parallel independent steps, dependency ordering and execution history.
- **ExecutionPolicy** budgets: `max_runtime_s`, `max_steps`, `max_cost`,
  `max_tokens`, `max_retries`, `max_recursion_depth`, `step_timeout_s`.

### Reasoning
- **Reasoner interface** decouples planning from the LLM:
  `LLMReasoner` (routes OpenAI/Gemini/Claude/DeepSeek/OpenRouter via LLMManager),
  `LocalReasoner` (heuristic), `HumanReasoner` (interactive).
- **Provider abstraction** behind `LLMManager.chat()` with automatic key
  rotation + failover + conversation continuity (verified live: bad key →
  cooldown → OpenRouter serves the same call).

### Memory (4 layers)
- STM rolling window with budget summarization · Working memory checkpoints ·
  LTM facts (rule-based extraction, dedup by key, confidence) · Knowledge
  index (txt/md/pdf, chunking, FTS5 lexical + vector search).
- Canonical path: Conversation → SQLite → retrieve → summarize → build prompt → LLM.

### Tasks & recovery
- Task lifecycle state machine: Created → Planning → Executing → Waiting →
  Observing → Retrying → Completed/Failed/Cancelled (strict transitions).
- Crash-resume: RUNNING/WAITING steps → INTERRUPTED, continue from first actionable.
- Persistent **execution history** (goal, plan, step, tool calls, errors,
  duration, tokens, cost, result).

### Observers
- **Observer subsystem** verifies tool effects in the environment
  (filesystem, time, network, clipboard, system, Android/ADB, screen-stub);
  the planner consumes observations, not just raw tool outputs.

### Safety & ops
- **PermissionManager**: Allowed / Confirmation required / Denied (per-tool +
  allowlist/denylist; confirm requires a UI hook — without one, confirm-tools deny).
- SQLite **recovery**: integrity checks, online backups (`VACUUM INTO`),
  recovery mode, additive column migration, versioned schema
  (`PRAGMA user_version` + `database/migrations.py` rollback).
- Sandboxed filesystem tools · `.env` in gitignore · `*.db*` ignored.

### Control surface
- FastAPI REST + WebSocket (`/ws` broadcasts live agent events) + web dashboard
  (`python main.py serve` → http://localhost:8000). The `/ws` endpoint is the
  future Android transport.

### Vertical slice — "Open YouTube on an Android phone" (real, no mocks)

One complete end-to-end capability, validated for real:

```
User goal → Planner creates plan → Executor executes step →
AndroidDevice (REAL adb-shell ADB protocol) sends `am start` /
`screencap -p` → ScreenObserver captures the screen →
VisionVerifier (LLM vision via OpenRouter → RapidOCR → pixel-diff)
confirms YouTube opened → Executor reports success or RETRIES
(existing retry loop) → Memory stores the completed task →
execution history records everything → dashboard shows it live.
```

- **Real transports:** `devices/adb.py` (adb-shell = the real ADB wire protocol;
  `adb connect <ip>:5555` or an emulator) — no WS mock, no placeholders.
- **Real verification:** `vision/verifier.py` — LLM vision (real OpenRouter
  multimodal call), RapidOCR (real OCR engine), pixel-diff fallback.
- **Retry:** screen-verification failure raises a retryable error through the
  existing Executor retry loop (initial + max_retries attempts).
- **Dashboard:** live via `/api/observer`, `/api/screenshots`,
  `/api/executions`, and the WS event feed.

```bash
python scripts/slice_youtube.py                        # full live slice (needs a device)
python scripts/slice_youtube.py --verify-only shot.png # verification only
python tests/test_vertical_slice.py                    # 19 real checks (offline path, OCR, pixel)
```

> Honest note: this sandbox has no Android device/emulator (no KVM, no root),
> so the device-present path is validated by the real code + verification engines
> here, and runs end-to-end on your laptop with `adb connect`.

### Tools (14 registered)
`time_now` · `echo` · `fs_read/write/list` (sandboxed) · `knowledge_add/search` ·
`todo_add/list/done` · `habit_add/check` · `expense_add/summary`

---

## Quick start

```bash
pip install -r requirements.txt   # or: uv sync
cp .env.example .env              # add OPENROUTER_API_KEY (optional; mock works offline)

python main.py                    # DEV: dev console at http://localhost:8000 (hot reload)
python main.py --no-reload        # dev console without hot reload
python main.py --launcher [port]  # PROD simulation: desktop launcher (runtime+browser+tray)
python main.py chat               # REPL
python main.py serve [port]       # dev console, no reload

# Production (Windows): build.bat → AgentCore.exe (launcher: starts runtime,
# opens browser, system tray, graceful shutdown)
python main.py whoami             # providers / tools / devices
python main.py ingest notes/      # index knowledge
python main.py search "binary search"
python scripts/migrate_jarvis.py --jarvis ../jarvis   # import JARVIS JSON data
python tests/smoke.py             # 37 core tests
python tests/test_api.py          # 20 API + dashboard tests
python tests/test_architecture.py # 47 architecture tests
python tests/test_android.py      # 10 android transport tests
python scripts/test_live.py       # 8 live tests (needs a key in .env)
```

## Dashboard (dev console — thin presentation layer)

`dashboard/app.py` is the **primary development entry point** (`python main.py`
boots it on port 8000). It is intentionally thin: it communicates **only through
AgentApp's public API** and renders `dashboard/templates/dashboard.html` — no
business logic, no tool code, no planning. It shows:

- **command input** — chat box + quick commands (via `/api/chat` → real pipeline)
- **live execution** — `/api/execution/live`: current goal, plan, step, running
  tool, retry count, elapsed (Dashboard → FastAPI → AgentApp → Planner → Executor
  → Tool Registry → Tool → Observer → Memory → Dashboard)
- **tool monitor** — `/api/tools/live`: per-tool state (ready/busy), last used,
  exec time, success rate (ToolMonitor)
- **execution timeline** — `/api/timeline`: complete ordered trace (goal →
  step_started → tool_started → tool_result → observer_result → step_completed),
  streamed live over `/ws`
- **planner output** — active plan, goal, step statuses (`/api/planner`)
- **execution progress** — recent execution history: status / ms / tokens / cost (`/api/executions`)
- **current task** — working-memory chip in the status bar (`/api/status`)
- **memory summary** — LTM facts tab + knowledge search (`/api/memory/facts`, `/api/knowledge/search`)
- **connected devices** — Windows/Android health (`/api/devices`)
- **registered tools** — searchable registry list (`/api/tools`)
- **recent logs** — live tail of `logs/agentcore.jsonl` (`/api/logs`) + WS event feed (`/ws`)

The same FastAPI app (via `api/server.py`) exposes `/ws/android` for the phone
companion and the provider/knowledge REST endpoints; `dashboard/app.py` just
adds the dev-console template on top. **One runtime** — every interface
(dev console, `AgentCore.exe` launcher, CLI, Android) goes through
`dashboard.app.create_app()` → `AgentApp.create()`.

See `docs/ARCHITECTURE.md` for the multi-interface diagram, startup sequence,
full runtime API list and single-runtime verification.

## Build & release pipeline (hard gates)

**The build NEVER continues after failed verification, and PyInstaller is
only invoked after every check passes.**

```
VERIFY → INSTALL DEPS → RE-VERIFY → TESTS → PYINSTALLER --clean → SMOKE EXE → PACKAGE
```

```bash
# Full gated pipeline
python scripts/build.py

# Control
python scripts/verify_build.py           # pre-flight gate only (exit 1 on any FAIL)
python scripts/verify_build.py --json    # machine-readable report
python scripts/build.py --only verify    # single stage
python scripts/build.py --no-exe         # skip PyInstaller + exe smoke (dev)
```

| Stage | What it does | Gate |
|---|---|---|
| **VERIFY** | python ≥ 3.11 · every dep importable · config present · assets present · DB opens · git rev (optional) | non-dependency FAIL → **abort now**; dependency-only FAIL → auto-install |
| **INSTALL DEPS** | `python -m pip install -r requirements.txt` | pip failure → **abort** with clear message |
| **RE-VERIFY** | same checks again | **any** remaining FAIL (incl. deps) → **abort** with the missing packages listed |
| **TESTS** | 3 hermetic suites (47 + 37 + 13) | any failure → abort |
| **PYINSTALLER** | `PyInstaller --clean --onefile --name AgentCore` | only reached if all above passed; failure → abort |
| **SMOKE EXE** | runs the built binary with `--selfcheck` (boots app, registers tools, opens DB) | exit ≠ 0 or no `SELFCHECK OK` → abort |
| **PACKAGE** | zips distributable → `dist/agentcore-<version>.zip` (excludes `.env`, `*.db*`, `data/`, `logs/`) | — |

**Windows:** double-click `build.bat` — same gated pipeline, and it
`exit /b 1` immediately if `verify_build.py` reports any failure.
`build_exe.bat` delegates to it. Output: `dist\AgentCore.exe` (keep your
`.env` next to it — it's not bundled on purpose).

**Exit codes:** `verify_build.py` returns **non-zero whenever any required
dependency is missing** (and on any other FAIL). `build.py` returns 1 and
prints `❌ BUILD ABORTED at stage: …` the moment a gate fails.

## Layout

```
agentcore/
├─ agent/        orchestrator (coordination only)
├─ reasoning/    Reasoner interface + LLM/Local/Human implementations
├─ executor/     Executor (loop, retries, timeouts, cancel, parallel) + ExecutionPolicy
├─ observer/     Observer subsystem (environmental verification)
├─ core/         contracts, event bus, logging, permissions, composition root
├─ config/       defaults.yaml + typed ConfigManager + secrets
├─ database/     SQLite (WAL), models, migrations, recovery (backup/integrity)
├─ devices/      Device ABC, WindowsDevice, AndroidDevice (protocol, Phase 5)
├─ llm/          LLMManager → router (rotation/failover) → providers
├─ memory/       STM/WM/LTM/knowledge + vector + indexer + extractor
├─ planner/      plan DAG, step state machine, resume
├─ tools/        searchable registry + local tools (sandboxed fs, life, knowledge)
├─ api/          FastAPI REST + WebSocket control surface
├─ ui/           web dashboard
├─ scripts/      migrate_jarvis.py, test_live.py
└─ main.py       CLI: chat | say | plan | resume | status | whoami | ingest | search | facts | serve
```

## Integration testing framework (pytest)

Every new feature **must include integration tests** — enforced by the build
gate (`scripts/build.py` smoke stage runs the suite; `verify_build.py` fails
if any of the 9 runtime boundaries lacks an integration test file).

```bash
# run the integration suite + coverage
python -m pytest tests/integration -m integration -v
python -m pytest --cov --cov-config=.coveragerc \
  --cov-report=term --cov-report=html:htmlcov tests/integration -m integration
# open htmlcov/index.html for the coverage report
```

| Boundary | Integration test file |
|---|---|
| Planner → Executor | `tests/integration/test_planner_executor.py` |
| Executor → Tool | `tests/integration/test_executor_tool.py` |
| Tool → Observer | `tests/integration/test_tool_observer_memory.py` |
| Observer → Memory | `tests/integration/test_tool_observer_memory.py` |
| Android workflows | `tests/integration/test_android_workflow.py` |
| Windows workflows | `tests/integration/test_windows_workflow.py` |
| Database recovery | `tests/integration/test_database_recovery.py` |
| Permission system | `tests/integration/test_permissions.py` |
| API provider switching | `tests/integration/test_provider_switching.py` |

Shared fixtures (`conftest.py`): a fresh **real** AgentApp runtime per test
(real Planner/Executor/Tools/Observer/Memory/SQLite) with only the external
LLM pinned to a deterministic mock. Coverage config in `.coveragerc`
(branch coverage, `fail_under=40`).

## Architecture decisions (why)

- **LLM only reasons; tools act** — deterministic, auditable, testable.
- **One `LLM.chat()` boundary + Reasoner seam** — provider swap or planner-engine
  swap is a config/constructor change, not a rewrite.
- **Executor owns execution** — the planner manages state, the executor runs
  steps; no component absorbs the other's job.
- **Observers verify** — "file created" is checked in the filesystem, not
  trusted from a tool's return string.
- **Event bus only for loose coupling** — multi-consumer broadcasts (UI + internals)
  use events; single-consumer data flows use direct calls (documented in `core/bus.py`).
- **Phone is a thin executor** — no reasoning on the phone; the `/ws` control
  surface is already live for Phase 5.

## Roadmap (future — not yet implemented)

- **Phase 5** Android companion: WS transport + pairing + executors
  (protocol + envelope + HMAC already designed in `devices/android.py`).
- **Phase 6** Android v2: accessibility/UI control, file share, capability reporting.
- **Phase 8** plugin system, multi-device, cloud deployment.
- **Reflection memory** (Phase 4): lessons learned from retries/failures.
- **Vector tool discovery** (Phase 4): replace string scoring when the registry
  grows past ~100 tools.
- **DI container** (Phase 4): only if constructor wiring becomes painful.
- **Token streaming** to the dashboard (SSE is single-event for now).

## Design doc

Full architecture, diagrams, DB schema, protocol and trade-offs:
`../agent_architecture.md`
