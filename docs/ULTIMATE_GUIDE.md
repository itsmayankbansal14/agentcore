# AgentCore — Ultimate Usage Guide
### How to drive this thing at its extreme capability

Everything below uses the **same one runtime**. Pick any interface — dev console,
CLI, desktop launcher, or (soon) your phone — and the agent behaves identically.

---

## 1. Quick start (3 commands)

```bash
pip install -r requirements.txt
cp .env.example .env        # paste your OPENROUTER_API_KEY (free at openrouter.ai/keys)
python main.py              # → dev console at http://localhost:8000 (hot reload)
```

That's it. You now have a planner + executor + memory + tools + observers +
multi-provider LLM behind one dashboard.

---

## 2. The interfaces (all one runtime)

| Interface | How | Best for |
|---|---|---|
| **Web dev console** | `python main.py` → :8000 | everything day-to-day (chat + panels) |
| **CLI** | `python main.py chat` | quick commands, scripting, `main.py say "..."` |
| **Desktop launcher** | `python main.py --launcher` (or `AgentCore.exe` on Windows) | feels like an app: opens browser + system tray |
| **Android** | companion app in `devices/companion_app/` → pairs over `/ws/android` | control your phone from the laptop |
| **API** | any HTTP/WS client → `localhost:8000/api/*` | build your own UI / voice / bots |

---

## 3. Talk to it — the command grammar

You don't need special syntax. The planner decomposes goals automatically:

```text
# Life admin (tools: todo_add/list/done, habit_add/check, expense_add/summary)
add todo finish DSA high priority
what's on my todo list?
add habit coding daily

# Knowledge / RAG — index your notes first, then ask questions from them
python main.py ingest ~/notes          # one-time: index txt/md/pdf/py…
what does my notes file say about binary search?

# Coding / execution
what time is it?                        # the model calls time_now tool
write a file called report.md with a weekly plan   # sandboxed fs tools

# Planning (the big one) — complex goals become persisted, resumable plans
build a flask app then write a README then zip it
# → 5 steps: virtual env → install flask → create app → README → zip
resume                                  # continue a saved plan after anything
python main.py plan "30 day DSA roadmap"  # CLI equivalent

# Phone control (after pairing, Phase 5/6)
open whatsapp on my phone
what notifications do I have?
tap at 100,200 on my phone              # accessibility UI control
take a screenshot of my phone

# Model / provider control
whoami                                  # which provider/model is active
# in .env: switch OPENROUTER_API_KEY / LLM_MODEL; the router fails over automatically
```

---

## 4. Extreme capability #1 — Multi-provider resilience

The LLM layer never cares which vendor answers. Configure several in `.env`:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
# optionally also: OPENAI_API_KEY=…, GEMINI_API_KEY=…, ANTHROPIC_API_KEY=…, DEEPSEEK_API_KEY=…
LLM_MODEL=openai/gpt-4o-mini
```

The router: tries providers in `config/defaults.yaml → llm.provider_priority`,
rotates keys, cools down rate-limited keys, and **replays the same conversation**
on failover — so a 429 mid-task never loses context. Watch it live in the
dashboard's Logs / event feed. `python scripts/test_live.py` proves the failover.

**Cost control** is enforced by the Executor policy:
`config/defaults.yaml → executor.*` (`max_runtime_s`, `max_steps`, `max_cost`,
`max_tokens`, `max_retries`, `max_recursion_depth`). No runaway loops, ever.

---

## 5. Extreme capability #2 — Memory that survives everything

- **STM** — conversation window, auto-summarized when it overflows.
- **Working memory** — current task/plan/step checkpointed to SQLite on every
  transition. Crash → `resume` continues exactly where it stopped.
- **LTM** — tell it about yourself once: *"my name is Aman, I live in Jaipur,
  I'm studying DSA"* → facts extracted, deduped, ranked by confidence, injected
  into every future prompt. `python main.py facts` to see them.
- **Knowledge** — `ingest` your PDFs/notes; the agent retrieves the right chunks
  (FTS5 + vector) and answers *from your documents*.

---

## 6. Extreme capability #3 — Android phone as a remote hand

1. Laptop: `python main.py` → `curl -X POST localhost:8000/api/devices/pair` → get 6-digit code.
2. Phone: open `devices/companion_app/` in Android Studio, run on device, enter
   `ws://<laptop-ip>:8000/ws/android` + the code.
3. Test without a phone: `python scripts/phone_sim.py --pair <CODE>`.

Commands: open app/url/youtube/whatsapp/settings · read notifications ·
foreground app · clipboard · share file · screenshot (MediaProjection) ·
**tap/swipe/type** (accessibility UI control). Privacy: notification access,
usage access, and accessibility are all **opt-in**; screenshots need a
per-session system grant.

Multi-device ready: pass `device_id` to any `android_*` tool (default `android`).

---

## 7. Extreme capability #4 — Extend it without touching the core

**Plugins** — drop a file in `plugins/`:

```python
# plugins/my_tool.py
from tools.base import Tool
from core.contracts import ToolResult

class MyTool(Tool):
    name = "my_tool"
    description = "Does my custom thing."
    parameters = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    async def execute(self, params, ctx):
        return ToolResult(ok=True, data={"echo": params.get("x")})

def register(registry, ctx):
    registry.register(MyTool())
```

Restart → the tool appears in `/api/tools`, is discoverable by the planner,
and is permission-gated like everything else. No core edits.

**New providers** — add one class in `llm/providers/` (copy any existing).

**New devices** — implement `devices/base.py` `Device` and register it;
`android.*` becomes `mydevice.*` automatically.

---

## 8. Build & ship

```bash
python scripts/build.py            # VERIFY → INSTALL → RE-VERIFY → TESTS → PYINSTALLER → SMOKE EXE → PACKAGE
build.bat                          # same on Windows → dist\AgentCore.exe
```

- The build **never proceeds past failed verification**.
- The exe is a **launcher**: starts the runtime, opens the dashboard in your
  browser, sits in the system tray, shuts down gracefully.
- Keep your real `.env` next to the exe (never bundled).

**Cloud:**
```bash
docker compose up --build          # same runtime on :8000, health-checked
```
Secrets via `docker-compose.yml` env (never baked into the image).

---

## 9. Security cheat-sheet

- `.env` is gitignored; keys live only on your machine / secret store.
- Tools are sandboxed (filesystem root = `data/sandbox`).
- `PermissionManager` gates everything: allowlist / deny per tool.
- Android: HMAC-signed envelopes, replay window, per-session grants.
- `*.db`, `dist/`, `build/`, `logs/` are gitignored.

---

## 10. The full check-up

```bash
python tests/test_architecture.py   # 47 — executor/policy/observer/permissions/recovery
python tests/smoke.py               # 37 — core loop, memory, migration, registry
python tests/test_api.py            # 26 — runtime APIs + dashboard + SSE streaming
python tests/test_android.py        # 12 — real WS transport + pairing + commands
python scripts/test_live.py         # 8 — real OpenRouter calls + failover + continuity
python scripts/verify_build.py      # pre-flight gate (exit 1 on anything broken)
```

> **130/130 checks green** at the time of writing.

---

## 11. If something breaks

```bash
git restore .                # undo uncommitted changes
git checkout <commit> -- <file>   # restore a file from history
python scripts/verify_build.py    # find what's broken
python main.py selfcheck          # runtime boot check
```
SQLite recovery: `database/recovery.py` (integrity check, `VACUUM INTO` backups,
backup restore) — automated backups + schema versioning included.
