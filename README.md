# AgentCore — Your Desktop AI Agent

AgentCore turns your Windows laptop into a personal AI agent that can manage
your tasks, browse the web, work with files, and control your Android phone —
all from one console. **It installs and bootstraps itself** — no manual setup.

---

## Installation

1. Install **Python 3.11 or 3.12** from https://www.python.org/downloads/
   (tick **"Add Python to PATH"**).
2. Extract the AgentCore package anywhere (e.g. `C:\AgentCore`).
3. **Done.** Everything else is automatic on first launch.

> Optional extras (both optional — AgentCore runs fine without them):
> - **Android control**: enable Developer options + USB debugging on your phone.
> - **API key**: for full AI answers, add `OPENROUTER_API_KEY=...` to `.env`
>   (copy from `.env.example`).

---

## Quick Start

| Action | Command |
|---|---|
| Launch (Windows) | double-click **`run.bat`** (or `AgentCore.exe`), or run `python main.py` |
| Open the console | it opens http://localhost:8000 automatically |
| Health check | `python main.py doctor` |
| Interactive chat | `python main.py chat` |

On first launch AgentCore automatically: creates `.venv`, installs
dependencies, installs the Playwright browser, creates the workspace, and
initializes the database — then starts. You never do this manually.

**Try saying:**
```
what time is it?
weather in Jaipur
add todo finish DSA high priority
copy hello world to clipboard
open youtube
open the browser to example.com and screenshot it
create a folder with a file, write, verify and delete it
open youtube on my phone        (requires Android setup)
```

> **Deterministic answers need no AI.** Single-intent requests
> (time, weather, todo, clipboard, open-youtube) are answered directly by
> their tools — the LLM is never invoked for them, so they work offline and
> never hallucinate.

---

## Doctor Command

`python main.py doctor` prints a full readiness report:

```
✓ python       READY      3.13
✓ venv         READY      deps present (bootstrapped)
✓ dependencies READY      all packages present
✓ playwright   READY      (optional) chromium installed (marker)
✓ adb          READY      (optional) adb transport available
✓ sqlite       READY      WAL supported
✓ openrouter   READY      API key configured
✓ browser      READY      (optional) chromium launches
✓ filesystem   READY      workspace writable
✓ tools          51 tools registered
✓ devices        windows=on, browser=on, android=off, adb=off
✓ dashboard      served at localhost:8000 (python main.py)
READY ✅
```

If anything is NOT READY, the report shows the exact fix (e.g.
`fix: pip install playwright && python -m playwright install chromium`).
The `browser` line runs a **real Chromium launch probe** — it never reports
READY when the browser cannot actually start (e.g. missing system libs).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Python not found` | Install Python 3.11+ and tick "Add Python to PATH" |
| Console won't open | `python main.py doctor` — check the report; ensure port 8000 is free |
| "no adb device" | Enable USB debugging on the phone, run `adb connect <ip>:5555` |
| Browser tools BROKEN | `python -m playwright install chromium` (or restart — bootstrap installs it once) |
| No AI answers | Add `OPENROUTER_API_KEY=...` to `.env` (free at openrouter.ai/keys) |
| Anything else | `python main.py doctor` shows the exact failing check + fix |

---

## Supported Features

- **Life admin** — todos, habits, expenses (SQLite, self-healing storage)
- **Filesystem** — create/write/read/verify/delete files in a sandbox
- **Weather** — real current weather for any city (Open-Meteo, no API key)
- **Clipboard** — set/get the desktop clipboard
- **Browser** — open, navigate, verify URL, screenshot (real Chromium)
- **Windows** — launch apps, detect/focus/close processes
- **Android** — wake, unlock, open apps/YouTube, notifications, screenshots,
  UI control (real ADB; optional)
- **Web + knowledge** — search your indexed notes/PDFs
- **Multi-provider AI** — OpenRouter / OpenAI / Gemini / Claude / DeepSeek
  with automatic failover and key rotation
- **Self-healing** — recoverable failures repair → retry → verify automatically
- **Target resolution** — "on my phone" → Android; otherwise Windows by default
- **Plugins** — drop a file in `plugins/` to add capabilities

---

## Android Setup

1. Phone: Settings → About → tap "Build number" 7× (enables Developer options).
2. Developer options → enable **USB debugging**.
3. Connect via USB, then: `adb connect <phone-ip>:5555` (same Wi-Fi) —
   or install our companion app from `devices/companion_app/`.
4. `python main.py doctor` should show `adb READY`.

---

## Browser Setup

AgentCore installs Chromium automatically on first launch (once). To force it:
```
python -m playwright install chromium
```

---

## Known Limitations

- **Android requires a real device or emulator** + USB debugging (not available
  in sandboxes/headless environments — tools report UNAVAILABLE, not errors).
- **Screenshots/UI-control on Android** need per-session grants (system dialogs).
- **Focus window** needs a desktop session (not available headless).
- Free-tier API models have rate limits (the runtime fails over automatically).

---

## Roadmap

- [x] Self-bootstrapping (one command) · doctor · dependency/tool/device health
- [x] Target resolution · self-healing · storage abstraction · observer authority
- [x] Windows installer preparation (`installer/AgentCoreInstaller.iss`)
- [ ] Signed `AgentCoreInstaller.exe` builds (CI)
- [ ] Voice input/output
- [ ] Cloud sync (Postgres adapter)

---

## Development (contributors)

```bash
python main.py --skip-boot   # skip bootstrap for fast dev iterations
python -m pytest tests/integration -m integration -v   # integration suite
python scripts/build.py      # verify → install → re-verify → tests → package (quality-gated)
python main.py doctor        # full readiness report
```

Architecture doc: `docs/ARCHITECTURE.md` · Ultimate guide: `docs/ULTIMATE_GUIDE.md`
