# AgentCore — TODO / Roadmap

Private personal project. Ordered by current milestone: **REAL PERSONAL USAGE**
(VOICE → AGENT → EXECUTION → OBSERVATION → VOICE).

Legend: `[ ]` not started · `[~]` in progress · `[x]` done (kept for context)

---

## Milestone: Real personal usage (current)

### Bootstrap correctness
- [~] `ensure_venv()` strict rule: frozen → bundled; inside `.venv` → continue;
      otherwise create + re-exec into `.venv`. Global deps are NEVER proof.
- [~] Python range enforced: `>= 3.11 AND < 3.13`; 3.13+ rejected.
- [x] Hermetic tests for: global-with-deps, no .venv, existing .venv, wrong
      version (3.10/3.13), correct version (3.11/3.12).
- [ ] Verify the full chain on a REAL Python 3.12 clean machine end-to-end
      (deps install inside the fresh venv was still failing in the last
      clean-run — see CONTEXT.md "Current status").

### Voice = primary interface
- [~] `voice/` subsystem exists (audio/stt/tts/wake/manager) with sync
      `run_once()`; `python main.py voice` works.
- [ ] `python main.py` should initialize the voice subsystem as the primary
      workflow (dashboard remains secondary transcript/inspection).
- [ ] Async voice API: `async run_once_async()` (+ optional `async run_loop()`);
      CLI wraps with `asyncio.run()`. No `asyncio.run()` inside core voice.
- [ ] Voice MVP reliability pass: mic → VAD → record → STT → normalized input
      → orchestrator → response → TTS → speaker.
- [ ] Windows acceptance procedure (`scripts/` or `tests/acceptance_voice.md`):
      speak "What time is it?" → transcript in chat, TimeTool, no LLM, spoken
      response; "Open YouTube." → browser + observer verification; "Open
      YouTube on my phone." → Android + observer verification.
- [ ] Verify TTS produces audible output on the real machine.
- [ ] Microphone recording test on real Windows hardware (VAD + sounddevice).

### Personal memory (keep current design — no redesign)
- [x] Structured Website (name, URL, description, purpose, usage, tags, notes,
      status, created_at) and Idea (title, description, tags, notes, status,
      created_at). Separate from working memory.
- [ ] Website discovery: when saving with only a URL, fetch page title /
      description / domain. Never fabricate; mark metadata unavailable on
      failure; no aggressive scraping; don't invent usage.
- [ ] Briefing relevance: add `related_project` field to saved items; active
      project → related items → briefing. No word-splitting heuristics.
- [ ] Startup briefing surfaces relevant personal memory (partial: printed at
      startup already; improve relevance via related_project).

### Direct router (capability-based, stop growing branches)
- [ ] Keep deterministic routing but move toward capability-based routing.
      Existing deterministic capabilities stay: time, weather, todo,
      clipboard, personal memory, browser/YouTube.
- [ ] Future tools should register a capability rather than a new if/elif in
      `planning/direct.py`.

### Target resolution
- [x] Default → Windows; explicit phone/android → Android; explicit browser →
      Windows browser.
- [x] Acceptance covered: "Open YouTube" → Windows browser; "Open YouTube on
      my phone" → Android; "Open YouTube on Windows" → Windows browser.
- [ ] Ensure TargetResolver controls ACTUAL execution (already does — verify
      with a live acceptance run).

### Release cleanup
- [ ] Build ZIP from a staging directory (or equivalent clean packaging).
- [ ] Verify the generated artifact itself (run acceptance against the ZIP
      contents, not the repo).
- [ ] Never include: .git, .env, .coverage, htmlcov, __pycache__, runtime DB,
      .db-wal, .db-shm, logs, ADB private keys, screenshots, developer files.
- [x] Release quality check exists in `scripts/build.py`.

### Tests (priority: vertical workflows over counts)
- [x] Hermetic integration: Voice → TimeTool → TTS (via seams, no hardware).
- [~] Voice → Windows Browser → Observer → TTS (needs Chromium libs; sandbox
      blocks launch — verify on Windows).
- [~] Voice → Android → Observer → TTS (needs device — report UNVERIFIED).
- [x] Voice → Save Website → SQLite → Briefing.
- [x] Voice → Save Idea → SQLite → Briefing.
- [ ] Real hardware acceptance tests on the dev machine (STT/TTS/mic/browser/
      android) — mark UNVERIFIED if they cannot be run, never PASS.

---

## Backlog (explicitly deferred)

- [ ] Wake word / continuous listening / barge-in / advanced VAD / noise
      suppression — ONLY after the basic speak→hear loop is reliable.
- [ ] Windows EXE + Inno Setup installer build (needs a Windows machine).
- [ ] GitHub push of local commits (needs a fresh classic PAT; revoke after).
- [ ] Android companion app polish (Kotlin).
- [ ] Voice button in the dashboard (when async voice API lands).
- [ ] Cloud sync / Postgres adapter (low priority).
- [ ] Signed installer builds (CI) — not needed for personal use.

---

## Known issues / environment gotchas

- Sandbox (this dev env): Linux, no KVM/root/apt, ~2 GB RAM (run test files
  one at a time to avoid OOM), Chromium system libs missing → browser tools
  BROKEN here but READY on Windows, no microphone/audio device.
- Sandbox resets installed pip packages between sessions; `data/`, `logs/`,
  `.venv/`, `dist/` are NOT in workspace snapshots — recreate after a reset
  (`python main.py` auto-bootstraps; `python scripts/build.py --only package`
  rebuilds the ZIP).
- Git identity resets each environment: `git config user.name "AgentCore"` +
  `git config user.email "agentcore@localhost"` before committing.
- Keep `pytest.ini`; conftest fixtures pin the LLM to a hermetic mock
  (`app.llm.router.keys = [KeyRuntime(...)]`).
- OpenRouter key lives in `.env`; faster-whisper STT needs no key; OpenRouter
  audio transcription needs ≥ $0.50 audio balance (402 otherwise).
