# AgentCore — Architecture

The architecture is **frozen**. Add features as new seams; do NOT redesign the
core components (Planner, Executor, Observer, Memory, Reasoner, Runtime,
Dashboard, DeviceManager, Tool Registry).

---

## 1. Design at a glance

**One runtime, many interfaces.** `AgentApp.create()` (in `core/app.py`) is the
single composition root. Every interface — CLI, dashboard (:8000), Android
companion, voice, REPL — talks to the same runtime object/API.

```
                    ┌──────────────────────────────┐
   Voice ──────────►│                              │──► Chat transcript
   Chat ───────────►│  Normalized User Input       │──► TTS → speaker
   CLI  ───────────►│         ▼                    │
                    │  Orchestrator (continuity)   │
                    │  Planner → Executor → Tools  │
                    │  TargetResolver ──► Device   │
                    │  Observer verification       │
                    │  Memory (STM/WM/LTM/Personal)│
                    └──────────────────────────────┘
                              │
                     SQLite (WAL + FTS5)
```

- **Deterministic fast-path** (`planning/direct.py`) runs BEFORE the LLM loop:
  unambiguous single-intent goals (time, weather, todo, clipboard, personal
  memory, open-youtube) are executed by their real tool with NO LLM call.
  Multi-intent/complex goals are never swallowed (complexity guard).
- **Task state** (`agent/task_state.py`) is persisted separately from the chat
  transcript. Follow-ups ("on my phone" after "open youtube") re-run the active
  task on the new target; ambiguous fragments ride the LLM path with full
  transcript context.
- **Personal memory** (`memory/personal.py`) is intentional user knowledge
  (websites/ideas/notes with structured fields), separate from working memory.

## 2. Component map

| Component | Location | Responsibility |
|---|---|---|
| Composition root | `core/app.py` | Builds every component; single `AgentApp.create()` |
| Orchestrator | `agent/orchestrator.py` | Session/plan lifecycle, task continuity, target resolution trigger |
| Task state | `agent/task_state.py` | Persisted active-task anchor (goal/target/plan/status) |
| Planner | `planner/planner.py` | Goal → persisted plan DAG; complexity detection |
| Direct router | `planning/direct.py` | Deterministic single-intent routing (no LLM) |
| Target resolver | `planning/target_resolver.py` | Intent → device (default Windows; explicit Android/browser) |
| Executor | `executor/executor.py` | The LLM↔tool loop, retries, timeouts, history, rollback |
| Recovery | `executor/recovery.py` | Repair → retry → verify for recoverable failures |
| Observers | `observer/` | Environmental verification (fs, time, network, clipboard, system, android, screen) |
| Memory | `memory/` | STM (messages), WM (working), LTM (facts), Knowledge (FTS5+vector), Personal |
| LLM | `llm/` | Manager, router (failover/rotation/cooldown), providers (openrouter/openai/gemini/claude/deepseek/ollama/mock) |
| Tools | `tools/` | Registry, base (guarded execute), health, monitor, local/, workflows/, android, personal |
| Devices | `devices/` | DeviceManager + windows / browser / android (WS) / adb (TCP) + Kotlin app |
| Vision | `vision/verifier.py` | Real screen verification: LLM vision → OCR → pixel-diff |
| Voice | `voice/` | audio (mic/WAV, VAD, playback), stt, tts, wake (deferred), manager |
| API | `api/server.py` | REST + SSE + WebSockets over the runtime |
| Dashboard | `dashboard/` | Thin dev console (transcript + inspection), no logic |
| Database | `database/` | SQLite WAL, models, versioned migrations, recovery |
| Config | `config/` | defaults.yaml ← local.yaml ← env; secrets via get_secret |

## 3. Startup sequence

`run.bat` → `python main.py` → `bootstrap.run()`:

1. **Python check** — requires `>= 3.11 AND < 3.13` (3.13+ rejected).
2. **Venv rule** — frozen → bundled; inside `AgentCore/.venv` → continue;
   otherwise create `.venv` if missing and **re-exec `main.py` with the venv
   interpreter** (`AGENTCORE_IN_VENV=1`). Global Python with deps installed is
   never treated as bootstrapped.
3. **Dependencies** — hash-gated install (`requirements.txt` change) +
   per-package missing install.
4. **Playwright** — install Chromium once (marker-gated); optional, never
   blocks.
5. **Workspace** — create all managed dirs.
6. **Database** — create if missing, migrations, WAL, integrity check.
7. **Doctor report** — printed; only unsupported Python hard-stops.
8. Launch the primary interface (currently the dev console at :8000; voice
   initialization is the target primary workflow).

## 4. Voice architecture

```
Microphone → audio.input (VAD end-of-speech) → WAV
  → stt (faster-whisper offline | openrouter whisper | vosk)
  → orchestrator.handle_user_message (SAME normalized input as chat)
  → response → tts (edge | sapi) → speaker (miniaudio; honest save fallback)
```

- The Planner/Executor never depend on mic/speaker code — the manager only
  calls the public orchestrator API.
- Voice input is normalized into the same representation chat uses; every
  response also lands in the chat transcript.
- Providers are injected seams (tests drive the full pipeline without
  hardware). Health is reported honestly per component.
- Wake word = declared seam, disabled (deferred). Async API (`run_once_async`)
  planned so the dashboard/runtime event loop can drive it.

## 5. Deterministic routing (capability direction)

Current `planning/direct.py` maps unambiguous intents to real tools:
time, weather, todo (add/list), clipboard (set/get), personal memory
(save website/idea/note, saved_list, briefing), open-youtube
(browser on Windows / android tool on phone). It consults the target device
and never fires for complex goals.

**Direction:** move to capability-based routing — future tools should register
a capability instead of adding another branch in `direct.py`.

## 6. Data model (key tables)

- `messages` — chat transcript (STM)
- `working_memory` — current task/plan/step (WM)
- `long_term_memory` — facts/preferences with confidence (LTM)
- `knowledge_documents` / `knowledge_chunks` + FTS5 + vector — indexed docs
- `plans` / `plan_steps` — persisted plan DAG with status machine
- `executions` / `tool_executions` — execution history + classified failures
- `sessions`, `devices`, `device_commands`, `audit_log`, `config_kv`
- `todos` / `habits` / `expenses` — life admin (self-healing storage)
- `saved_items` — personal knowledge (kind, title, url, description, purpose,
  usage, tags, notes, status, created_at)
- `task_state` — active task anchor (goal, target, plan, status)

Migrations are additive, versioned (`PRAGMA user_version`); new tables are
auto-created by `create_all()` on existing DBs.

## 7. Key invariants

- No mocked execution in production paths; optional components report
  BROKEN/UNAVAILABLE honestly — never fake success.
- The Executor is the only place that runs tools; observers verify effects.
- Tool names are underscore-only.
- Playwright tools use the async API (sync API refuses inside asyncio);
  cross-call browser/process state lives in module-level dicts keyed by
  session_id.
- Tests pin the LLM to a hermetic mock; integration tests exercise the REAL
  runtime (real tools, real SQLite, real observers).
- Coverage `fail_under=40`; every feature needs integration tests;
  `scripts/verify_build.py` maps the boundaries.

## 8. Release packaging

`python scripts/build.py` (verify → install → re-verify → tests → package;
`--only <stage>` works). The ZIP is quality-gated: no `.git`, `.env`,
`.coverage`, `htmlcov`, `__pycache__`, runtime DB, `.db-wal/.db-shm`, logs,
screenshots, ADB keys, or developer files. Direction: build from a clean
staging directory and verify the artifact itself.

## 9. Deviations from earlier docs

- `docs/ARCHITECTURE.md` and `docs/ULTIMATE_GUIDE.md` remain as historical
  docs; this file is the living reference.
