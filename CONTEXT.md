# AgentCore — Project Context

Read this first. It explains what AgentCore is, the product direction, current
status, and the environment facts that shape every decision.

---

## What AgentCore is

**"A personal computer agent that I talk to."**

AgentCore is a **private, personal** AI agent that runs on the owner's Windows
laptop, can control an Android phone, and is **voice-first**: speak → it
listens → thinks → acts → verifies → answers out loud. Chat/dashboard is the
secondary transcript and inspection surface.

It is NOT a product for distribution: no multi-user support, no public APIs,
no plugin marketplace, no generic installer UX, no enterprise architecture.
Reliability and maintainability matter, but engineering effort goes to actual
personal usage.

### Core principles
1. **Voice is the primary interface**; chat is the secondary transcript/context
   view and a fallback input.
2. **The LLM is a reasoning component**, not the whole agent. Deterministic
   requests (time, weather, todo, clipboard, save/brief, open-youtube) are
   answered by their real tools with NO LLM call.
3. **Task state is persistent and structured** — never reconstructed from the
   chat transcript. Follow-ups ("on my phone") modify the active task.
4. **Personal knowledge is intentional** — the user explicitly saves ideas /
   websites / notes; AgentCore stores them structurally and briefs concisely.
5. **Windows is the default execution environment**; Android is selected
   explicitly when requested.
6. **Reliability and real-world execution beat feature count.** No mocks, no
   placeholders, no fake success — optional components report UNAVAILABLE /
   BROKEN honestly.

---

## Product direction (as of latest milestone)

Target workflow:

```
Launch AgentCore
  → Voice subsystem initializes
  → Microphone ready
  → User speaks
  → STT → AgentCore → Execution → Observer verification
  → Response → TTS → User hears
```

- `python main.py voice` should NOT be required for normal use — the primary
  launch should drive this workflow, with the dashboard remaining available.
- Wake word, continuous listening, barge-in, advanced VAD/noise suppression:
  **deferred** until the basic speak→hear loop is reliable.
- Personal memory MVP is good enough — no redesign; small improvements only
  (website metadata, `related_project` for briefing relevance).
- Direct router: keep deterministic routing but move to **capability-based**
  registration instead of more if/elif branches.

---

## Current status (2026-08-14)

### Done and verified
- Bootstrap: strict venv rule + Python range `>= 3.11 and < 3.13` implemented;
  14 hermetic rule tests + acceptance suite green.
- Voice subsystem built and tested hermetically; **real speech round-trip
  verified** in the sandbox: edge-tts synthesized "open youtube on my phone" →
  faster-whisper transcribed it exactly (~3.5 s, offline, no key).
- Personal memory (save website/idea/note, saved_list, briefing) + task
  continuation + deterministic router — 111 pytest + 186 custom checks green
  at last full run.
- Live dashboard runs on :8000 (0.0.0.0) with 56 tools registered.

### Known gaps / in-progress
- **Clean-machine deps install inside a fresh 3.12 venv was failing** in the
  last clean-run (`installed missing: [...] FAILED`); individual package
  installs work. Root cause not yet confirmed — pip inside the fresh venv
  (probably a slow/transient install window or index issue during the
  parallel-ish install batch). Verify the full chain on a real 3.12 machine.
- Voice is not yet the automatic primary entry — `python main.py` still
  launches the dashboard (by design until async voice + acceptance verified).
- Async voice API (`run_once_async`) not yet implemented.
- Website metadata enrichment and `related_project` briefing not yet added.
- Capability-based router refactor not yet started.
- Windows-only items are UNVERIFIED in this sandbox: real microphone capture,
  audible TTS output, real browser open, real Android execution.

---

## Repository layout

```
agent/            orchestrator + task_state (continuity)
api/              FastAPI runtime API (same app serves dashboard/CLI/Android)
config/           layered YAML config (defaults/local/env)
core/             composition root (AgentApp), contracts, bus, errors,
                  permissions, workspace, dependencies, plugins, logging
dashboard/        dev console (thin presentation layer) @ :8000
database/         SQLite (WAL + FTS5), models, migrations, recovery
devices/          DeviceManager + windows/browser/android(WS)/adb transports,
                  Kotlin companion app
executor/         execution loop, policy, recovery, history
llm/              LLMManager, router (failover/rotation), providers
memory/           STM/WM/LTM, knowledge indexer, vector, personal (saved_items)
observer/         environmental verification observers
planning/         Planner + direct.py (deterministic router) + target_resolver
plugins/          auto-discovered tool plugins (weather)
reasoning/        reasoner seams (LLM/local/human)
tools/            registry, base, health, monitor, local/, workflows/, storage/,
                  android_tools.py, personal.py
vision/           real screen verification (LLM vision / OCR / pixel-diff)
voice/            audio (input/VAD/output), stt, tts, wake, manager
scripts/          build.py, verify_build.py, runtime_audit.py,
                  verify_direct_path.py, test_live.py, capability_demo.py,
                  phone_sim.py
tests/            pytest suites + standalone scripts + integration/
ui/               dashboard template + legacy JARVIS inspiration
```

---

## Environment facts (this sandbox — not the user's machine)

- Linux, headless, ~2 GB RAM, no root/apt/KVM. Cannot build Windows EXEs, run
  real Android devices, or install Chromium system libs (browser launch is
  BROKEN here; READY on Windows).
- Python 3.13.14 is the sandbox default; **AgentCore requires 3.11/3.12**.
  A real 3.12 interpreter is available via uv for verification:
  `uv python install 3.12`.
- Installed pip packages are **not persisted** between sessions; `data/`,
  `logs/`, `.venv/`, `dist/` are excluded from workspace snapshots. After any
  reset: `python main.py` re-bootstraps; `python scripts/build.py --only
  package` rebuilds the ZIP; playwright chromium may need `python -m playwright
  install chromium` again.
- RAM is tight: run test files one at a time (the full pytest run can OOM).
- Git identity resets each session: set
  `git config user.name "AgentCore"` + `git config user.email
  "agentcore@localhost"` before committing.

---

## Key external facts

- **OpenRouter key** is in `.env` (OpenAI-compatible, base URL
  `https://openrouter.ai/api/v1`). LLM default model `openai/gpt-4o-mini`.
  OpenRouter audio transcription requires ≥ $0.50 audio balance (else 402) —
  STT default is faster-whisper (offline, free) to avoid this.
- Open-Meteo provides weather (free, no key). edge-tts provides neural TTS
  (free). Playwright Chromium is the browser engine.
- Tool names must be underscore-only (dotted names are rejected by
  OpenAI-compatible APIs): `time_now`, `todo_add`, `android_open_youtube`…
