# AgentCore — Working Agreement for AI Agents / Contributors

Rules for anyone (human or AI) modifying this codebase. Read CONTEXT.md and
ARCHITECTURE.md first.

---

## 1. Product constraints (non-negotiable)

- **Private, personal project.** No public distribution, no multi-user
  support, no public APIs, no plugin marketplace, no generic installer UX,
  no enterprise architecture, no abstraction for hypothetical users.
- **Voice-first.** Voice is the primary interface; chat/dashboard is the
  secondary transcript + inspection surface.
- **Windows default; Android explicit.** Default execution target is Windows;
  Android only when the user explicitly asks.
- **Reliability > features.** No mocks in production paths, no placeholders,
  no fabricated success. Optional components report BROKEN/UNAVAILABLE
  honestly (with a fix hint).
- **Freeze the architecture.** Never redesign Planner, Executor, Observer,
  Memory, Reasoner, Runtime, Dashboard, DeviceManager, or Tool Registry.
  Add features as new seams only.

## 2. Coding rules

- **Deterministic requests bypass the LLM.** Time/weather/todo/clipboard/
  personal-memory/open-youtube route through `planning/direct.py` to their
  real tool. Verify with a "bomb" provider in tests (raises if consulted).
- **Tool names are underscore-only** (dotted names rejected by OpenAI/
  OpenRouter): `time_now`, `todo_add`, `android_open_youtube`.
- **Playwright** must use the **async API** (`playwright.async_api`) — the sync
  API refuses inside asyncio. Cross-call state (browser, processes) lives in
  module-level dicts keyed by `session_id` (the executor passes a fresh ctx per
  call).
- **Task state** lives in the `task_state` table — never reconstruct execution
  state from the chat transcript.
- **Personal memory** stays separate from working memory; structured fields
  only (see ARCHITECTURE.md §6).
- **Don't grow `planning/direct.py` with more if/elif branches** — new
  deterministic tools should register a capability instead.
- **No `asyncio.run()` inside core** (voice or runtime) — the CLI may wrap with
  it; core exposes async APIs.
- Do not leave `TODO`/`FIXME`/`pass`/`NotImplemented`/placeholder/mock
  production blockers. Legitimate exception handlers with `pass` are fine;
  label clearly.
- Keep `python-dotenv`, `pyperclip`, etc. as **declared** requirements, not
  transitive deps.

## 3. Tests

- Every feature needs integration tests; `scripts/verify_build.py` maps the
  boundaries; coverage `fail_under=40` in `.coveragerc`.
- Conftest fixtures pin the LLM to a hermetic mock:
  `app.llm.router.keys = [KeyRuntime("mock", "mock-key", "mock-1")]`.
- **MockProvider queue is consumed by the real Planner's LLM decompose on
  complex goals** — prepend `'[ECHO]'` to mock queues, or pad with
  `"[ECHO]"` lines.
- Integration tests run the REAL runtime (real tools, real SQLite, real
  observers); only the LLM is mocked.
- Keep `pytest.ini` (markers integration/unit; `-p no:cacheprovider` used).
- Real-hardware tests that cannot run must be marked **UNVERIFIED / skipped**,
  never claimed as PASS.
- RAM is tight (~2 GB sandbox): run test files one at a time rather than the
  whole suite at once to avoid OOM kills.

## 4. Bootstrap / environment

- Supported Python: `>= 3.11 AND < 3.13`. 3.13+ must be rejected. (The sandbox
  default is 3.13 — use `uv python install 3.12` for real verification.)
- Venv rule: frozen → bundled; inside `AgentCore/.venv` → continue; otherwise
  create `.venv` and re-exec `main.py` inside it. **Global deps are never
  proof of bootstrapping.**
- `python main.py` auto-bootstraps; `--skip-boot` skips for fast dev
  (still dispatchable before subcommands: `python main.py --skip-boot doctor`).
- After an environment reset: reinstall pip deps (list in CONTEXT.md),
  `python scripts/build.py --only package` to rebuild the ZIP, and possibly
  `python -m playwright install chromium`.
- Git identity resets each session:
  `git config user.name "AgentCore" && git config user.email
  "agentcore@localhost"`.

## 5. README rule

**Do not update the README until the behavior actually works.** The README must
exactly match implemented functionality — no claims for unverified features.

## 6. Tooling cheat-sheet

| Task | Command |
|---|---|
| Dev console | `python main.py` (or `--no-reload`) |
| Full readiness | `python main.py doctor` |
| Tests (pytest) | `python -m pytest tests/... -p no:cacheprovider` |
| Standalone suites | `python tests/test_architecture.py`, `tests/smoke.py`, `tests/test_api.py`, `tests/test_android.py`, `tests/test_vertical_slice.py`, `tests/test_reliability.py` |
| Build verify | `python scripts/verify_build.py` |
| Package ZIP | `python scripts/build.py --only package` |
| Runtime audit | `python scripts/runtime_audit.py` |
| Direct-path check | `python scripts/verify_direct_path.py` |
| Voice (debug) | `python main.py voice [--loop]` |
| Personal memory | `python main.py briefing`, `python main.py saved [kind]` |
