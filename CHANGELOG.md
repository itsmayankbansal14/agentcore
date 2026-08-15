# AgentCore — Changelog

All notable changes to AgentCore. Private personal project. Format follows
[Keep a Changelog](https://keepachangelog.com/) loosely; versions are
informal until v1.0.

---

## [Unreleased / In progress]

### Milestone: Personal real-usage (in progress)
- **Bootstrap correctness** — `ensure_venv()` no longer treats a global Python
  with installed deps as "bootstrapped". Rule is now strict: frozen → bundled
  runtime; interpreter inside `AgentCore/.venv` → continue; otherwise create
  `.venv` and re-exec `main.py` inside it. Supported Python range enforced:
  `>= 3.11 AND < 3.13` (3.13+ rejected with a clear message).
- **Voice as primary interface (in progress)** — `python main.py` should
  initialize the voice subsystem as the primary workflow instead of launching
  straight into the dashboard; dashboard stays as the secondary transcript/
  inspection surface. Async voice pipeline (`run_once_async`) planned.
- **Real voice acceptance procedure** — Windows hardware test script for
  Speak → STT → agent → execution → verification → TTS → hear.
- **Website metadata enrichment** — when saving a website with only a URL,
  fetch page title/description/domain (no fabrication; unavailable marked as
  such).
- **Briefing relevance** — explicit `related_project` field on saved items;
  active project → related items → briefing (no word-splitting heuristics).
- **Capability-based direct router** — stop growing `planning/direct.py` with
  if/elif branches; future tools register capabilities instead.
- **Release staging** — ZIP built from a clean staging directory; verify the
  artifact itself.

---

## [0.1.0] — 2026-08-07 (latest stable)

### Added
- **Deterministic fast-path** (`planning/direct.py`): single-intent goals
  (time, weather, todo, clipboard, open-youtube, personal memory) run their
  real tool WITHOUT the LLM — verified with a "bomb" provider that raises if
  consulted.
- **Real weather** (`plugins/weather.py`): Open-Meteo geocoding + forecast,
  WMO code mapping, no API key, honest failure offline. Replaced random mock.
- **Desktop clipboard** (`tools/local/clipboard.py`): `clipboard_set` /
  `clipboard_get` (pyperclip), capability `clipboard`, honest failure on
  headless systems.
- **Voice subsystem** (`voice/`): `audio/` (mic + WAV sources, energy-based
  VAD, miniaudio playback), `stt/` (faster-whisper offline default, OpenRouter
  whisper option, vosk option), `tts/` (edge neural default, Windows SAPI5
  fallback), `wake/` (deferred seam), `manager.py` (VoiceManager pipeline).
  `python main.py voice [--loop]`.
- **Personal memory** (`memory/personal.py`, `tools/personal.py`): structured
  saved items (website/idea/note/resource/project/discovery) with url, purpose,
  usage, tags, notes, status, created_at; concise `briefing()`; CLI
  `python main.py briefing` / `saved [kind]`; startup briefing printed.
- **Task continuation** (`agent/task_state.py`): persisted `task_state` table
  separate from chat transcript; "Open YouTube." → "On my phone." re-runs the
  active task on Android.
- **Doctor launch probe** (`core/dependencies.py`): real Chromium launch check
  in `python main.py doctor` — never reports READY when the browser can't
  start.

### Fixed
- `python main.py --skip-boot <cmd>` printed usage instead of running the
  command (flag was stripped only from the bootstrap gate, not dispatch).
- `scripts/build.py --only <stage>` was a silent no-op (stage function was
  hardcoded `None`).
- `android_open_youtube` required a `query` param; now optional (opens home).
- `.env.example` lacked `OPENROUTER_API_KEY` (README referenced it).
- `python-dotenv` was only a transitive dependency (silent `except: pass` in
  config); now declared.
- Stale "Screen observer is a stub" docstring (it is real: ADB screencap +
  VisionVerifier).
- Doctor printed `fix:` lines under READY items; now only on failures.
- VAD speech_seconds double-divided frames → wrong duration.
- `miniaudio.SampleFormat.SIGN16` → `SIGNED16`; generator must be primed
  before `PlaybackDevice.start()`.
- Microphone availability check ran after imports, so `python main.py voice`
  crashed with a traceback instead of the honest "no microphone" message.

### Verified
- Clean-machine bootstrap: extract ZIP → `python -S main.py` → .venv created →
  deps installed → Playwright chromium → workspace → SQLite (WAL, integrity
  ok) → dashboard HTTP 200 — zero manual steps.
- Real speech round-trip: edge-tts "open youtube on my phone" → faster-whisper
  transcribed exactly in ~3.5 s (offline, no key).
- Tests: 111 pytest (12 acceptance + 74 integration + 25 voice/personal/
  continuation) + 186 custom checks green; `verify_build.py` 9/9; release ZIP
  quality-gate clean.

---

## [0.0.x] — earlier phases (summarized)

### Self-bootstrapping / productization
- `bootstrap.py`: venv → deps (hash-gated) → playwright (once) → workspace →
  database → doctor; re-exec targets `main.py`.
- `run.bat` / `run.ps1` one-command launchers; `AgentCore.exe` = launcher only.
- `core/dependencies.py` DependencyManager (READY/INSTALLING/MISSING/BROKEN).
- `installer/AgentCoreInstaller.iss` Inno Setup prep (build on Windows).
- End-user README; `docs/ARCHITECTURE.md`, `docs/ULTIMATE_GUIDE.md`.

### Target resolution + self-healing
- `planning/target_resolver.py`: explicit phone/browser/windows intent →
  device; default Windows; offline fallback with honest reason.
- `executor/recovery.py` RecoveryPolicy: repair → retry → verify, classified
  failures with suggestions; rollback hooks.
- `core/workspace.py` WorkspaceManager (single path authority);
  `tools/storage/todo_storage.py` self-healing SQLite todos.

### Multi-interface runtime + debugging console
- Single `AgentApp.create()` composition root; dev console on :8000 with
  Planner/Executor/Observer/Tool/Target/Device/Health/Timeline/Logs panels;
  SSE live stream; `/api/runtime`, `/api/executor`, `/api/observer`,
  `/api/executions`, `/api/tools/health`, `/api/deps`.

### Vertical slice (real Android path)
- `devices/adb.py` real ADB over TCP (adb-shell); `vision/verifier.py` real
  LLM-vision/OCR/pixel-diff screen verification; `android_open_youtube`
  verification gate with retries; phone-sim test harness.

### Capabilities + reliability + integration framework
- 4 real workflows through the full pipeline (fs, windows process, browser,
  android); pytest integration suite with hermetic mock LLM; coverage
  `fail_under=40`; `scripts/verify_build.py` boundary mapping.

### Phase 5/6 — Android companion + plugins + multi-device
- WebSocket `AndroidDevice` with HMAC-signed envelopes; Kotlin companion app
  scaffold (`devices/companion_app/`); plugin manager auto-discovers
  `plugins/`; device manager facade.

### Initial commit
- Desktop-first AI agent platform: Planner, Executor, Observer, Memory,
  Reasoner, Runtime, Dashboard, Tool Registry, structured logging, event bus,
  SQLite (WAL + FTS5), permissions.
