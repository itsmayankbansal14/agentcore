# AgentCore — Desktop-First AI Agent Architecture
### Windows laptop controller + Android remote companion
**Design document v1.1** — incorporates reviewer critique (device abstraction, event-driven orchestrator, tool-registry search, JARVIS migration path). Architecture & implementation plan only — no implementation code written yet.

> **v1.1 deltas:** §2.6 redefined as a Device Manager (`device.execute(...)`, Windows/Android/future); §2.1 orchestrator made explicitly event-driven; §2.4 tool registry gains search/capability routing; `devices/` + `events/` added to folder structure; §12 adds trade-offs; new §15 (critique → design response) and §16 (JARVIS → AgentCore migration path).

---

## 0. Executive Summary

AgentCore is a **desktop-first, LLM-agnostic AI agent** that runs on a Windows laptop and treats an Android phone as a *thin remote executor*.

**Guiding principles:**

1. **The LLM only reasons.** It never stores memory and never touches devices directly. Everything the LLM "wants" to do is expressed as a structured tool call that the **Tool Manager** validates and executes.
2. **One abstraction boundary.** The rest of the app talks to `LLM.chat()`. Providers (OpenAI / Gemini / Claude / DeepSeek / local) are interchangeable behind that interface, with automatic key rotation and failover.
3. **Everything that matters is persisted.** Conversation, task state, plans, preferences, facts, and device state live in SQLite with WAL journaling — so the agent can crash and resume mid-task.
4. **The phone is a peripheral.** The Android app is a command executor with no brain of its own: connect, receive, execute, report.

**This design deliberately separates:** reasoning (LLM) · state (memory) · action (tools) · transport (communication) · policy (config) — so any one of them can be replaced without touching the others.

---

## 1. System Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│                              WINDOWS LAPTOP (AgentCore)                            │
│                                                                                    │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐  │
│  │   UI Layer  │  │   AGENT      │  │  MEMORY      │  │  LLM MANAGER            │  │
│  │  CLI/TUI    │──│  ORCHESTRATOR│──│  MANAGER     │  │  ┌───────────────────┐  │  │
│  │  Web Dash   │  │  (session,   │  │  STM / WM    │  │  │  Provider Router  │  │  │
│  │  (optional) │  │   loop)      │  │  LTM / Know. │  │  │  Key Rotation     │  │  │
│  └─────────────┘  └──────┬───────┘  └──────┬───────┘  │  │  Failover / Retry │  │  │
│                          │                 │          │  └─────────┬─────────┘  │  │
│                          ▼                 ▼          │            ▼            │  │
│                ┌─────────────────┐   ┌──────────┐    │   ┌──────────────────┐   │  │
│                │   TASK PLANNER  │   │ SQLite   │    │   │ OpenAIProvider   │   │  │
│                │  decompose /    │   │ (WAL) +  │    │   │ GeminiProvider    │   │  │
│                │  resume / state │   │ vectors  │    │   │ ClaudeProvider    │   │  │
│                └────────┬────────┘   └──────────┘    │   │ DeepSeekProvider  │   │  │
│                         │                            │   │ OllamaProvider    │   │  │
│                         ▼                            │   └──────────────────┘   │  │
│                ┌─────────────────┐                   │         │                │  │
│                │   TOOL MANAGER  │◄──────────────────┼─────────┘ (tool schemas) │  │
│                │  registry /     │                   │                           │  │
│                │  allowlist /    │                   │                           │  │
│                │  sandbox        │                   │                           │  │
│                └───────┬─────────┘                   └───────────────────────────┘  │
│                        │                                                           │
│            ┌───────────┼───────────────┐                                           │
│            ▼           ▼               ▼                                           │
│  ┌──────────────┐ ┌────────────┐ ┌──────────────┐  ┌────────────────────────────┐  │
│  │ LOCAL TOOLS  │ │  DEVICE    │ │  PLUGIN      │  │ CONFIG + LOGGING & RECOVERY│  │
│  │ files, shell,│ │  MANAGER   │ │  LOADER     │  │ env/secrets · audit log ·   │  │
│  │ calendar,    │ │ Windows ·  │ │  (future)    │  │ checkpoint journal ·        │  │
│  │ browser, etc.│ │ Android · …│ │              │  │ crash recovery             │  │
│  └──────────────┘ └─────┬──────┘ └──────────────┘  └────────────────────────────┘  │
└─────────────────────────┼──────────────────────────────────────────────────────────┘
                          │  WebSocket (TLS) + REST, paired & authenticated (AndroidDevice)
                          ▼
┌────────────────────────────────────────────────────────────────────────────────────┐
│                        ANDROID PHONE (Companion App)                              │
│                                                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────────────────────┐   │
│  │  Background  │  │  COMMAND     │  │  EXECUTORS (thin — no reasoning)         │   │
│  │  Service     │  │  EXECUTOR    │  │  ┌───────────┐ ┌──────────────┐         │   │
│  │  (foreground │  │  queue + ack │──│  │ AppOpener │ │ NotifReader │         │   │
│  │   + WS)      │  │  + result    │  │  │ Screenshot│ │ FileShare    │         │   │
│  └──────────────┘  └──────────────┘  │  │ Clipboard │ │ IntentLauncher│        │   │
│                                       │  └───────────┘ └──────────────┘         │   │
│                                       │  + PermissionManager (Accessibility /   │   │
│                                       │    NotificationListener / MediaProjection)│  │
│                                       └─────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Responsibilities

### 2.1 AI Agent — Orchestrator (Laptop)
The **execution loop and session brain**. Owns the conversation loop: accept input → build context → call LLM → dispatch tool calls → observe results → repeat until the task is finished.

- Session management (multiple concurrent sessions, one per task thread).
- The agent loop state machine:
  `NEW → PLANNING → EXECUTING → WAITING_TOOL → BLOCKED → COMPLETED | FAILED`
- Decides *when* to ask the planner, *when* to call the LLM, *when* to retry.
- **Event-driven coordination** (per reviewer): subscribes to the event bus — `user_message_received`, `tool_result`, `step_completed`, `step_failed`, `provider_failed`, `device_offline` — and reacts by scheduling the next coordination step. The orchestrator **orchestrates; it never implements domain logic** (no voice/music/routing/config code lives here).
- **Never** calls providers directly; **never** touches devices directly — it composes Memory Manager + Task Planner + Tool Manager + LLM Manager.

### 2.2 Memory Manager (Laptop)
Single entry point for **all** persistence. Implements the layered memory (see §7) and exposes a uniform API:

```
memory.load_context(session)  -> ContextBundle (STM window + WM state + relevant LTM + knowledge)
memory.remember(fact)         -> LTM upsert with dedup/confidence
memory.update_working(session, state) -> checkpoint (atomic, WAL)
memory.search_knowledge(query, k) -> top-k chunks (vector + FTS5)
memory.summarize_overflow(session) -> LLM-assisted compaction of STM
```

**Canonical prompt-build path** (per reviewer): `Conversation → SQLite → retrieve relevant history (+ WM state + LTM facts + knowledge chunks) → summarize overflow → build prompt → LLM`. The LLM never reads memory directly — it receives an assembled context bundle (see §7).

### 2.3 LLM Manager (Laptop)
The **only** module that knows about providers. Exposes one interface used everywhere:

```
llm.chat(messages, tools=None, session_id=None) -> LLMResponse {content, tool_calls, usage}
llm.stream(...)       # streaming variant
llm.embed(text)       # for memory/knowledge vectors
```

- **Provider registry**: OpenAI, Gemini, Claude, DeepSeek, Ollama (local) + "OpenAI-compatible" catch-all for future vendors.
- **Routing & failover**: if a call fails (rate limit, quota, 5xx, timeout), it classifies the error and automatically retries with another configured key or provider, **replaying the same normalized message list** so conversation continuity is preserved. See §8.
- **Normalized message format**: the app always passes `[{role, content, tool_calls?, tool_result?}]`; providers adapt to their native formats.

### 2.4 Tool Manager (Laptop)
The **action boundary**. A registry of tools, each declared with a JSON Schema (so the LLM can call them via function calling) and a permission level.

- `ToolRegistry.register(Tool)` — tool = `{name, description, input_schema, execute(params, ctx)}`.
- **Registry is searchable** (per reviewer): `tool.search(query)` / `tool.describe(name)`. The planner/LLM are shown only tools matching the current plan step and the user's permission level — this is what keeps 50+ tools manageable instead of a hardcoded keyword chain.
- **Capability-targeted routing**: every tool declares a `capability` (e.g. `filesystem`, `device.android.open_app`). The same logical tool call can be routed to whichever device can serve it via `device.execute(...)` — the agent never hardcodes "android".
- **Validation** before execution: schema check, parameter bounds, allowlist/permission check, quoting/safety for shell.
- **Idempotency & retries**: tools declare `idempotent` and `retryable`; Tool Manager handles retries with backoff and records every execution in `tool_executions`.
- Execution is **agent-side only** — the LLM proposes, the Tool Manager disposes.
- Ships with local tools (files, shell/sandbox, web fetch, calendar/email stubs) and the `android.*` tool family that routes through the Android Dispatcher.

### 2.5 Task Planner (Laptop)
Breaks goals into **persisted, resumable plans**.

- Decomposes a natural-language goal into a DAG of subtasks (steps) with dependencies.
- Each step is a unit of work the agent can complete in one loop iteration (small enough to be atomic for resumability).
- State per step: `PENDING → RUNNING → WAITING_TOOL → DONE | FAILED | BLOCKED`, with an `attempts` counter and per-step checkpoint blob.
- On resume after crash: reads the plan from SQLite, marks `RUNNING` steps as `INTERRUPTED`, and continues from the first non-`DONE` step.
- Human-in-the-loop: `BLOCKED` steps can request clarification or permission.

### 2.6 Device Manager (Laptop) — Windows / Android / future platforms
A **device abstraction** so tools target *capabilities*, not hardware — the reviewer's `device.execute(...)`, implemented as:

- `Device` ABC: `connect() · execute(command) · disconnect() · capabilities() · health()`.
- `WindowsDevice` — wraps local-machine tools (files, shell, browser) as a device, so "control my laptop" and "control my phone" are the *same conceptual operation*.
- `AndroidDevice` — the phone link: pairing, WebSocket client, command dispatch, reconnection, heartbeat. It exposes the `android.*` capability family, but the agent only ever calls `device.execute("android.open_app", {...})`.
- `DeviceManager` — registry of connected devices, online/offline transitions, per-device command queues, result correlation back to the originating tool call. Unreachable device ⇒ tools report `BLOCKED` (a status, not a crash).
- **Future**: `LinuxDevice`, `CloudDevice`, `SmartHomeDevice` (MQTT transport) are new `Device` classes + capability families — never new orchestrator branches.

### 2.7 Android Companion App (Phone)
A **thin executor daemon**, no LLM, no memory of its own beyond a local command log.

- Foreground service (sticky, with persistent notification) holding the WebSocket connection and command executor.
- Executors map command → Android API (intents, accessibility, notification listener, MediaProjection, SAF).
- Reports results as structured JSON back over the same channel; screenshots/files streamed in chunks or via URL.
- Pairing/security client (see §9).

### 2.8 Configuration Manager (Laptop)
Single source of truth for configuration, layered:

1. `config/defaults.yaml` — shipped defaults.
2. `config/local.yaml` — machine-specific overrides (ignored by git).
3. Environment variables / secrets store (Windows DPAPI or OS keyring for API keys; never plaintext in repo).
4. Runtime overrides (e.g., "switch provider") with validation and reload hooks.

Exposes typed access (`config.get("llm.provider_priority")`) so components never read env vars directly. Secrets are decrypted only inside the LLM Manager and Config Manager.

### 2.9 Logging & Recovery (Laptop)
- **Structured logging**: JSONL to `logs/` (one line per event: `ts, session, component, event, detail`), human-readable console mirror, log rotation.
- **Event sourcing for agent state**: every state transition (message added, tool started/finished, step completed) is an event appended to the store — this is what makes recovery deterministic.
- **Crash recovery**: SQLite in WAL mode + periodic `working_memory` checkpoints + an "agent heartbeat" journal. On startup, the Orchestrator runs `recover(session)` which reconciles any `RUNNING`/`INTERRUPTED` work.
- **Audit log**: tool executions and device commands are immutable audit entries.

---

## 3. Data Flow Diagram

### 3.1 Normal command loop (no tools)

```
 User                    Orchestrator        Memory            LLM Manager          Provider
  │  "What's my plan      │                   │                    │                  │
  │   for the week?"      │                   │                    │                  │
  │──────────────────────▶│  load_context()   │                    │                  │
  │                       │──────────────────▶│                    │                  │
  │                       │  ContextBundle    │                    │                  │
  │                       │◀──────────────────│                    │                  │
  │                       │  llm.chat(msgs)   │                    │                  │
  │                       │────────────────────────────────────────▶│                 │
  │                       │                    │                    │  HTTP/WS to API  │
  │                       │                    │                    │────────────────▶│
  │                       │                    │                    │◀────────────────│
  │                       │  reply + save msg │                    │                  │
  │                       │──────────────────▶│  store_message()   │                  │
  │  reply ◀──────────────│                    │                    │                  │
```

### 3.2 Tool-execution loop with Android control

```
 Orchestrator    LLM Manager        Tool Manager        Android Comm Layer        Phone App
      │   llm.chat(msgs+tools)          │                     │                      │
      │────────────────────────────────▶│                     │                      │
      │   tool_calls:                   │                     │                      │
      │   [{android.open_app,           │                     │                      │
      │     {app:"whatsapp"}}]          │                     │                      │
      │◀────────────────────────────────│                     │                      │
      │  validate + permit              │                     │                      │
      │────────────────────────────────▶│                     │                      │
      │                                 │  dispatch(cmd)      │                      │
      │                                 │────────────────────▶│  WS send envelope     │
      │                                 │                     │──────────────────────▶│
      │                                 │                     │  ack {id}            │
      │                                 │                     │◀──────────────────────│
      │                                 │                     │  execute (Intent)     │
      │                                 │                     │  result {id, ok, data}│
      │                                 │◀────────────────────│◀──────────────────────│
      │  store tool_result in msg       │                     │                      │
      │────────────────────────────────▶│  (memory)           │                      │
      │  loop: llm.chat(msgs w/ result) │                     │                      │
```

### 3.3 Crash-recovery flow

```
 Startup → Orchestrator.recover()
   → Memory: load working_memory (last checkpoint)
   → Planner: any step in RUNNING/WAITING_TOOL → INTERRUPTED
   → Log: "recovered session X at step Y"
   → Continue: re-issue LLM call with context + "resume from step Y"
```

---

## 4. Communication Protocol (Laptop ↔ Android)

### 4.1 Comparison

| Criterion | REST (HTTP) | WebSocket | MQTT |
|---|---|---|---|
| Model | request/response | full-duplex, persistent | pub/sub via broker |
| Latency (first byte) | ~1 RTT + polling delay | ~1 RTT, then instant | ~1 RTT + broker hop |
| Push from phone (events, notifications) | ❌ needs polling | ✅ native | ✅ native |
| Connection overhead | stateless, re-auth per call | one-time handshake | persistent broker session |
| Correlation of request↔response | easy (HTTP) | easy (message ids) | needs manual request/response pattern |
| Broker dependency | none | none | **requires broker** (Mosquitto/cloud) |
| Multi-device fan-out | manual | manual | ✅ built-in topics |
| Offline/queue behavior | client-side | app-level | ✅ broker QoS 0/1/2 |
| Complexity on Android | low | medium | medium |
| Auth/TLS | standard | standard | standard + broker ACL |

### 4.2 Recommendation: **WebSocket (wss://) as primary, REST as auxiliary**

**Why WebSocket wins here:**
- The dominant pattern is *laptop sends command → phone executes → phone replies* with sub-second expectations, plus *phone pushes events* (notification arrived, screenshot ready). WebSocket is the only protocol that gives **both directions on one persistent low-latency channel** without polling.
- No broker to deploy — the laptop *is* the server (or the phone connects to a relay in remote mode). Fewer moving parts for a 1:1 pairing.
- MQTT shines at *many-to-many* fan-out with broker-managed queues — we adopt it later if the user runs multiple PCs/devices with a home broker; the command layer is protocol-agnostic by design.

**REST stays for:** discovery/handshake, pairing bootstrap, uploading large files (multipart, resumable), health checks. Same auth as WS.

### 4.3 Message envelope (JSON, versioned)

```json
{
  "v": 1,
  "id": "cmd_8f2a1c",              // correlation id
  "type": "command",                // command | ack | result | event | heartbeat | error
  "device": "pixel-7-<fingerprint>",
  "cmd": "android.open_app",
  "params": { "app": "whatsapp", "data": "https://wa.me/919..." },
  "ts": "2026-08-06T10:15:30Z",
  "auth": { "token": "<HMAC(session_token, id+ts)>" },
  "expires": "2026-08-06T10:15:40Z"
}
```

- Every command gets an immediate `ack` and a later `result` (or `error`) carrying the same `id`.
- `heartbeat` every 15–30 s; timeout ⇒ reconnection with exponential backoff.
- Large payloads (screenshots) use `chunked` events or a REST upload URL rather than one giant WS frame.

### 4.4 Discovery & Pairing

- **LAN**: mDNS/DNS-SD advertises `_agentcore-laptop._tcp`; the phone app discovers it (or the user scans a QR code shown by the laptop UI containing `ws://<ip>:<port>` + a one-time pairing code).
- **Pairing handshake**: QR/one-time code → both sides derive a **device secret** → device gets a persistent **device token** (random 256-bit) stored in the app's Keystore. Laptop stores `devices` table entry with the token hash.
- **Remote (phone not on home Wi-Fi)**: recommend **Tailscale/WireGuard mesh** (phone connects to the same private network) — no public port forwarding, full TLS inside the tunnel. Alternative: a small cloud relay that forwards encrypted envelopes without being able to read payloads (end-to-end keyed).

### 4.5 Authentication & Encryption

- **Transport**: TLS 1.3 (`wss://`), certificate pinning on the Android app (self-signed CA generated at pairing time, or ACME cert on the relay).
- **Per-message auth**: HMAC-SHA256 over `id + payload + ts` with the shared device token → replay protection via `expires` + nonce window.
- **Secrets**: API keys → OS keyring (Windows DPAPI / Android Keystore). Device tokens → Keystore. Never in config files.
- **Threat model**: assume the LAN is semi-trusted (home Wi-Fi) but a compromised network must not reveal payloads → always TLS even on LAN; token never sent over plaintext.

---

## 5. Folder Structure

```
agentcore/
├─ agent/                    # Orchestration core (no IO policy, no provider knowledge)
│  ├─ orchestrator.py        #   agent loop / state machine
│  ├─ session.py             #   session lifecycle, context assembly
│  ├─ loop.py                #   LLM↔tool loop driver
│  └─ recovery.py            #   crash recovery bootstrap
├─ memory/                   # Memory Manager + stores
│  ├─ manager.py             #   unified memory API (load_context/remember/update/search)
│  ├─ stm.py                 #   short-term: rolling window + summarizer
│  ├─ working.py             #   working memory: task/plan/step checkpoints
│  ├─ ltm.py                 #   long-term: facts/prefs/projects w/ dedup+confidence
│  ├─ knowledge.py           #   file/pdf/notes index + chunking
│  └─ vector.py              #   embeddings + vector store adapter (sqlite-vec / chroma)
├─ llm/                      # LLM Manager — THE ONLY provider-aware module
│  ├─ manager.py             #   LLM.chat/stream/embed facade
│  ├─ router.py              #   provider priority, failover, key rotation
│  ├─ providers/
│  │  ├─ base.py             #   Provider ABC (chat/stream/embed/count_tokens)
│  │  ├─ openai_provider.py  #   OpenAI + OpenAI-compatible (DeepSeek, Groq, …)
│  │  ├─ gemini_provider.py
│  │  ├─ claude_provider.py
│  │  └─ ollama_provider.py  #   local LLM
│  └─ schema.py              #   normalized message types (Pydantic)
├─ planner/                  # Task Planner
│  ├─ planner.py             #   goal → plan DAG
│  ├─ steps.py               #   step state machine
│  └─ resume.py              #   plan continuation after crash
├─ tools/                    # Tool Manager + tool families
│  ├─ registry.py            #   register/validate/dispatch
│  ├─ permissions.py         #   allowlist, consent prompts
│  ├─ local/                 #   files, shell (sandboxed), web, notes, …
│  ├─ android/               #   android.* tool family → dispatcher
│  └─ plugins/               #   user-installed tool plugins
├─ devices/                  # Device Manager — capability-targeted execution
│  ├─ base.py                #   Device ABC: connect/execute/capabilities/health
│  ├─ manager.py             #   registry, online state, queues, result correlation
│  ├─ windows.py             #   WindowsDevice (local machine tools as a device)
│  └─ android/               #   AndroidDevice: protocol + companion app
│     ├─ protocol.py         #   envelope (de)serialization, HMAC
│     ├─ pairing.py          #   QR/one-time-code handshake
│     ├─ dispatcher.py       #   per-device queue + correlation
│     └─ companion_app/      #   (optional) checked-in Kotlin app source
├─ events/                   # event bus — the orchestrator's coordination fabric
│  ├─ bus.py                 #   in-process pub/sub, typed events
│  ├─ events.py              #   event schemas (user_message, tool_result, …)
│  └─ handlers.py            #   subscriptions from orchestrator/planner/devices
├─ database/                 # persistence layer
│  ├─ connection.py          #   SQLite WAL, migrations
│  ├─ models.py              #   ORM (SQLAlchemy) models
│  ├─ repositories.py        #   typed data access for each store
│  └─ migrations/            #   versioned schema migrations
├─ config/                   # Configuration Manager
│  ├─ defaults.yaml
│  ├─ local.yaml             #   (gitignored machine overrides)
│  ├─ manager.py             #   typed get/set, reload, env/secrets merge
│  └─ secrets.py             #   OS keyring integration
├─ logs/                     # Logging & Recovery
│  ├─ agentcore.jsonl        #   structured event log
│  ├─ audit.jsonl            #   tool/device audit trail
│  └─ journals/              #   agent heartbeat + checkpoint journals
├─ api/                      # local control surface
│  ├─ server.py              #   FastAPI: REST + WS for UI/remote
│  └─ ws.py                  #   phone connection endpoint
├─ ui/                       # optional local web dashboard (FastAPI static)
├─ plugins/                  # plugin loader (entry-points based)
├─ main.py                   # CLI entry point
├─ pyproject.toml            # packaging (uv/pip)
└─ README.md
```

**Why `android/` sits at top level:** the laptop↔phone protocol is a first-class boundary (like the LLM boundary), not a hidden tool detail. The Kotlin app source lives there so the protocol definitions (`protocol.py` and the Kotlin mirror) stay in one reviewable place.

---

## 6. Database Schema (SQLite)

**Engine choice:** SQLite, WAL mode, foreign keys on, `busy_timeout`. One database `agentcore.db` (plus optional separate `knowledge.db` if it grows large). Migrations via Alembic.

```
sessions
  id TEXT PK            session_uuid
  name TEXT             user label
  created_at, last_active
  working_memory_id FK -> working_memory.id

conversations
  id TEXT PK            session-scoped thread
  session_id FK
  title TEXT

messages
  id INTEGER PK AUTOINC
  conversation_id FK
  role TEXT             system|user|assistant|tool
  content TEXT
  tool_calls JSON       NULL for non-assistant
  tool_results JSON     NULL
  provider TEXT         which provider served this turn (for audit/continuity)
  model TEXT
  tokens INTEGER
  created_at
  INDEX(conversation_id, id)

working_memory                 -- one row per active session
  id INTEGER PK
  session_id FK UNIQUE
  current_task TEXT
  current_plan_id FK -> plans.id
  current_step_id  FK -> plan_steps.id
  state JSON                  -- arbitrary checkpoint blob
  updated_at

plans
  id INTEGER PK
  session_id FK
  goal TEXT
  status TEXT         ACTIVE|COMPLETED|ABANDONED
  created_at, completed_at

plan_steps
  id INTEGER PK
  plan_id FK
  parent_id FK NULL   -- DAG
  title TEXT
  status TEXT         PENDING|RUNNING|WAITING_TOOL|BLOCKED|DONE|FAILED|INTERRUPTED
  attempts INTEGER
  checkpoint JSON
  order_idx INTEGER
  created_at, finished_at

long_term_memory
  id INTEGER PK
  session_id FK
  kind TEXT           preference|fact|project|identity
  key TEXT            normalized key for dedup (e.g. "pref.daily.start_time")
  content TEXT
  embedding BLOB      (vector; optional if vector db external)
  source TEXT         where learned from
  confidence REAL     0..1
  updated_at
  UNIQUE(session_id, kind, key)

knowledge_documents
  id INTEGER PK
  name TEXT, path TEXT, mime TEXT, sha256 TEXT, size INTEGER
  indexed_at

knowledge_chunks
  id INTEGER PK
  doc_id FK
  chunk_index INTEGER
  content TEXT
  embedding BLOB

llm_providers                 -- runtime state, not secrets
  id INTEGER PK
  provider TEXT         openai|gemini|claude|deepseek|ollama|openai_compatible
  model TEXT
  priority INTEGER
  enabled BOOLEAN
  key_ref TEXT          reference to keyring entry (never the key itself)
  consecutive_failures INTEGER
  cooldown_until TEXT   NULL
  last_error TEXT
  last_used_at

tool_executions              -- audit + idempotency
  id INTEGER PK
  session_id FK
  plan_step_id FK NULL
  tool TEXT
  args JSON, result JSON, status TEXT
  started_at, finished_at
  error TEXT

devices
  id INTEGER PK
  name TEXT, fingerprint TEXT UNIQUE
  device_token_hash TEXT
  last_seen, connection_state TEXT
  capabilities JSON      (which executors the app reported)

device_commands            -- command queue log (laptop side)
  id INTEGER PK
  device_id FK
  cmd TEXT, params JSON, status TEXT
  envelope_id TEXT, result JSON
  created_at, executed_at

config_kv
  key TEXT PK, value TEXT, updated_at

audit_log
  id INTEGER PK, ts TEXT, actor TEXT, action TEXT, target TEXT, detail JSON
```

**Why these tables matter for the requirements:** `plan_steps` + `working_memory` = crash-resume. `llm_providers` + `messages.provider` = continuity across provider switches. `device_commands` = correlation + audit. `tool_executions` = idempotency + audit.

---

## 7. Memory Design

| Layer | What it holds | Where | Lifecycle | Used for |
|---|---|---|---|---|
| **Short-term (STM)** | Recent conversation (last N messages, token-budgeted) | `messages` rows + in-memory window | Rolling window; LLM summarization when it overflows | Current turn context |
| **Working (WM)** | Current task, plan, current step, step checkpoint | `working_memory` + `plan_steps.checkpoint` | Persisted on **every** state transition (WAL) | Resume after crash; continuity |
| **Long-term (LTM)** | Preferences, facts, project info | `long_term_memory` + embeddings | Dedup by key; confidence decay; consolidation job | Persistent personalization |
| **Knowledge** | Files, PDFs, notes, docs | `knowledge_documents` + `knowledge_chunks` + vector index | Added by indexing job; re-index on hash change | RAG: semantic retrieval into context |

**Flow in a typical turn:**
1. `load_context()` → STM window + WM state + top-k LTM (keyword + vector) + top-k knowledge chunks.
2. Context assembled as system + history; everything the model needs to *remember* is already in the prompt; the model is **never** asked to be the store.
3. After the turn: new messages appended; any new fact candidate extracted by a lightweight `remember()` path (LLM extraction run only on user turns, async).
4. On overflow: STM is summarized (map-reduce) and the summary is stored as a synthetic message; the window keeps the tail.

**Vector strategy:** default = `sqlite-vec` (zero-ops, same file, FTS5 for lexical) for MVP; adapter interface allows swapping to Chroma/Qdrant for cloud scale. Embeddings come from `LLM.embed()` so they follow provider rotation too.

---

## 8. API (LLM) Abstraction Design

### 8.1 The contract

```python
@dataclass
class LLMMessage:        # normalized, provider-agnostic
    role: str            # system | user | assistant | tool
    content: str | None
    tool_calls: list[ToolCall] | None
    tool_call_id: str | None

@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    usage: Usage | None
    provider: str
    model: str
    finish_reason: str

class LLMManager:        # the ONLY public face
    async def chat(self, messages: list[LLMMessage], tools: list[ToolSpec] | None = None,
                   session_id: str | None = None) -> LLMResponse: ...
    async def stream(self, ...) -> AsyncIterator[str]: ...
    async def embed(self, text: str) -> list[float]: ...
    async def count_tokens(self, text: str) -> int: ...
```

ToolSpec is a JSON Schema (`name, description, parameters`) — identical shape to what OpenAI/Gemini/Claude accept (with per-provider translators inside each provider class).

### 8.2 Provider classes

```
BaseProvider (ABC)
  ├─ OpenAIProvider        # openai SDK (also serves any /v1/chat/completions clone)
  ├─ GeminiProvider        # google-genai
  ├─ ClaudeProvider        # anthropic SDK
  ├─ DeepSeekProvider      # = OpenAI-compatible with deepseek base_url
  └─ OllamaProvider        # local via ollama HTTP
```

Each implements `chat/stream/embed/count_tokens` against its native SDK and translates the normalized message list **to** its format and **back**. This is the only file per vendor you ever edit to add a provider.

### 8.3 Router: failover + key rotation

```
LLM.chat(messages, tools, session_id)
  for provider in priority_order(provider_healthy):
      for key in key_pool(provider, skip_in_cooldown):
          try:
              resp = provider.chat(messages, tools)
              mark_success(provider, key)
              return resp
          except RateLimit / QuotaExceeded:
              mark_cooldown(key, provider)         # try next key/provider
          except AuthError:
              mark_cooldown(key)                   # bad key, don't hammer
          except Timeout / ServerError / Transient:
              retry same key with backoff, then next provider
  else: raise AllProvidersFailed  → agent surfaces "providers exhausted"
```

- **Continuity across switches is free** because the *message list lives in the session*, not inside any provider — the router simply replays the same `messages` to the next provider. If a long conversation exceeded the new provider's context window, the router inserts the STM summary as a synthetic system message before retrying.
- **Health tracking** is persisted in `llm_providers` (consecutive failures, cooldown) so a rate-limited key isn't tried again for N minutes even across restarts.
- Streaming failure mid-stream: signal `interrupted`, retry from last complete message with `max_tokens` remainder.

---

## 9. Android Companion Design

### 9.1 App architecture (Kotlin, Jetpack Compose)

```
CompanionApp
├─ ConnectionManager      # OkHttp WebSocket + REST client, TLS pinning, reconnection w/ backoff
├─ PairingFlow            # QR scan / one-time code → derive device token → Keystore
├─ CommandExecutor        # command → executor mapping; queue + ack/result correlation
├─ Executors
│  ├─ AppOpener           # package lookup + launch intents (no special permission for most)
│  ├─ IntentLauncher      # url/intent deep links (youtube://, wa.me, settings panel intents)
│  ├─ NotificationReader  # NotificationListenerService → typed notification objects
│  ├─ ScreenCapture       # MediaProjection → screenshot PNG (user-granted, per-session)
│  ├─ ClipboardManager    # set/get clipboard text
│  ├─ FileShare           # SAF "open document" → share/copy file, return content URI/stream
│  └─ Extras (future)     # SMS, calls, media controls, DND toggles
├─ PermissionManager      # requests & explains each permission; reflects grant state to laptop
├─ LocalLog               # Room (SQLite) log of recent commands/results (crash-local only)
└─ MainActivity           # minimal UI: connection status, pairing, permission status
```

### 9.2 Command set (v1)

| Command | Android mechanism | Permission needed |
|---|---|---|
| `android.open_app(app)` | `getPackageManager().getLaunchIntentForPackage` | none (most apps launchable) |
| `android.open_url(url)` | `ACTION_VIEW` intent | none |
| `android.open_youtube(query)` | `youtube://` or web intent | none |
| `android.open_whatsapp(number)` | `wa.me` intent | none |
| `android.open_settings(panel)` | settings panel intents | none |
| `android.read_notifications(since)` | NotificationListenerService | **Notification Access** |
| `android.screenshot()` | MediaProjection + VirtualDisplay | **Screen capture** (user-granted each session) |
| `android.get_foreground_app()` | UsageStatsManager | **Usage Access** |
| `android.set_clipboard(text)` / `get_clipboard` | ClipboardManager | Android 13+: small toast prompt |
| `android.share_file(path)` | SAF + FileProvider | **Storage** (SAF picker) / none via provider |

### 9.3 Permissions — why each exists, and how it's integrated cleanly

- **Notification Listener Service** (`NotificationListenerService`): required to *read* notifications — Android gives no other API to observe them. Declared in manifest, user enables in Settings → Notifications → Notification access. Integrated behind `NotificationReader`; the app streams notification events as `event` messages to the laptop only when user opted in ("mirror notifications" toggle).
- **Accessibility Service**: needed for *reading screen contents* / *performing UI actions* (e.g., "tap the send button", "scroll"), and for reliably intercepting events other intents can't reach. It is **not** needed for the v1 command set (open app/URL/settings, notifications, screenshot) — so it ships **disabled by default** and is only requested when the user enables "UI control" features, keeping the privacy surface minimal. Always: no password fields captured; data stays on device except explicitly forwarded commands.
- **MediaProjection** (screen capture): system shows a "start recording/casting?" dialog every session by design; cannot be silently granted. Integrated with a 5-minute idle expiry and auto-release.
- **Usage Access**: only to answer "what app is in the foreground" — used by `get_foreground_app`; optional, degrades gracefully.
- **Storage (SAF)**: for `share_file` the user picks a file via the system picker (SAF) — no broad storage permission needed on modern Android; FileProvider for sending app-owned files.

Every permission is requested lazily, only when the user first uses the feature, with an explainer. Grant state is reported to the laptop (`devices.capabilities`) so the agent can say "phone has notification access: no" instead of silently failing.

### 9.4 Result reporting & large payloads

- Results are typed: `{ok: true, data: {...}}` or `{ok: false, error: {code, message}}` with stable error codes the planner can branch on.
- Screenshots/files: WS chunked transfer or a REST `POST /files` upload from the phone → laptop stores under `data/uploads/`, returns a `file://` ref the tool result carries. Laptop persists and indexes it (knowledge memory hook).

---

## 10. Suggested Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language (laptop) | **Python 3.11+** (asyncio) | AI ecosystem, SDKs, fast iteration; agent workloads are IO-bound |
| API server (laptop) | **FastAPI + Uvicorn** | REST + native WebSocket in one framework, Pydantic schemas shared with tools |
| Persistence | **SQLite (WAL) + SQLAlchemy + Alembic** | zero-ops local, transactional, crash-safe; single-user fits perfectly |
| Vectors | **sqlite-vec** (MVP) → Chroma/Qdrant (scale) behind `memory/vector.py` | same-file first; swappable |
| LLM SDKs | openai / google-genai / anthropic + OpenAI-compatible fallbacks | thin wrappers behind `BaseProvider` |
| Config/secrets | pydantic-settings + **Windows DPAPI/keyring** | typed config, keys out of files |
| Logging | structlog → JSONL + rotating files | structured, queryable |
| Events | in-process async event bus (pydantic-typed); durable via SQLite journal | orchestrator coordinates, never implements |
| Packing | **uv** for deps; PyInstaller optional | simple, reproducible |
| Android | **Kotlin, Jetpack Compose, Ktor/OkHttp, Room, Hilt, WorkManager, DataStore** | modern stack; WS client; Keystore |
| Discovery | **mDNS (python-zeroconf)** + QR pairing | zero-config on home LAN |
| Remote link | **Tailscale/WireGuard** (or cloud relay later) | secure private mesh, no port forwarding |
| Messaging format | **JSON (v1)** with schema versioning; protobuf as an upgrade path | debuggable, human-readable |

---

## 11. Development Roadmap (MVP → Production)

| Phase | Scope | Exit criteria |
|---|---|---|
| **0 — Foundations** | Project skeleton, config manager, logging, **in-process event bus**, SQLite + migrations, LLM Manager with **OpenAI-compatible** provider, `LLM.chat()` | `llm.chat("hi")` works with 1 provider; events flow; structured logs exist |
| **1 — MVP Agent** | Orchestrator loop, STM + working memory, Tool Manager + 3 local tools (files, shell-sandbox, web fetch), CLI | Can hold a conversation, remember within session, execute local tools, survive Ctrl-C and resume |
| **2 — Memory depth** | LTM (facts/prefs), knowledge indexing (PDF/notes), vector search, STM summarization | Remembers preferences across sessions; answers from a PDF |
| **3 — Planner + recovery** | Task decomposition, plan DAG, checkpoint/resume, BLOCKED/human-in-loop | "Plan a 30-day DSA grind" → persisted plan; crash mid-task → resumes at the right step |
| **4 — Multi-provider** | Gemini/Claude/DeepSeek/Ollama providers, router with key rotation + failover + continuity test | Kill the primary key → next provider serves the same conversation |
| **5 — Android v1** | Companion app: pairing, WS, AppOpener/IntentLauncher/NotificationReader/screenshot; laptop dispatcher + `android.*` tools | "Open WhatsApp on my phone" works; notifications stream to laptop |
| **6 — Android v2** | Accessibility-based UI control, file share, clipboard, capability reporting, remote-over-Tailscale | Full v1 command set + consent-driven UI control |
| **7 — Surface** | Web dashboard, voice I/O (STT/TTS), streaming responses | Feels like a product |
| **8 — Extensibility & scale** | Plugin system, browser/email/calendar tools, multi-device, multi-PC, cloud deployment (Postgres + broker) | Each new capability is a plugin/tool addition, not a rewrite |

---

## 12. Design Decisions & Trade-offs

| Decision | Why | Trade-off / mitigation |
|---|---|---|
| **LLM only reasons; tools act** | Keeps memory/actions deterministic, auditable, testable; LLMs are unreliable executors | Slightly more plumbing; worth it for correctness |
| **One `LLM.chat()` boundary** | Provider swap = config change, not code change; enables rotation | Normalization layer must be maintained per provider |
| **Python + SQLite, not C#/Postgres** | AI ecosystem; single-user local fits SQLite perfectly | Python startup/perf for heavy CPU — offloaded to subprocesses; Postgres adapter later |
| **WebSocket over MQTT/REST** | True bidirectional low-latency 1:1 without broker infra | MQTT adapter later for many-device fan-out; envelope format is transport-agnostic |
| **Phone = thin executor** | Security (no keys on phone), simpler app, single reasoning brain | Requires reliable link; offline phone = tools BLOCKED (by design, surfaced clearly) |
| **JSON envelope (not protobuf) v1** | Debuggable, versionable, Kt/Py interop trivial | Size/CPU overhead negligible for command traffic; protobuf path reserved |
| **SQLite + sqlite-vec (not Qdrant/Chroma) first** | Zero-ops, one file, transactional with the rest | Vector recall at scale needs the external store — swap via `memory/vector.py` adapter |
| **Event-sourced agent state** | Deterministic recovery; audit trail | More writes; batched via WAL + checkpoint journal |
| **Event-driven orchestrator** | Orchestrator reacts to events instead of implementing branches — no 4,000-line `if/elif` chain | Indirection; mitigated with typed event schemas |
| **Device abstraction (`device.execute`)** | Tools target capabilities, not hardware; Android is one implementation, future devices slot in | Extra indirection; pays off at the 2nd device/platform |
| **Tool registry search** | 50+ tools stay discoverable by planner/LLM without keyword chains | Requires schema discipline per tool |
| **STTM summarization** | Bounds tokens; continuity across context windows | Summary lossy → kept as synthetic message, raw rows retained |
| **mDNS + QR pairing, LAN-first** | Zero-config, private, no cloud dependency | Remote requires Tailscale/relay — documented path |
| **Secrets in OS keyring** | Keys never in repo/config | Slightly more setup per machine; Config Manager abstracts it |
| **Accessibility off by default** | Minimal privacy surface; user opts into UI control | UI-control features gated behind explicit enable |

**Anti-goals (deliberately not in v1):** agent-initiated payments, background app *silent* screenshots without user consent, running the LLM on the phone, cloud-only operation.

---

## 13. Extensibility Map (future features → which seam)

| Future feature | Seam it plugs into | Change needed |
|---|---|---|
| Voice assistant | `ui/` + `tools/local/` (STT/TTS tool) | new tool + UI panel |
| Browser automation | `tools/local/browser_tool.py` | new tool (Playwright adapter) |
| Email automation | `tools/local/email_tool.py` | new tool + OAuth config |
| Calendar integration | `tools/local/calendar_tool.py` | new tool |
| Smart home control | `android/`-style device adapter (MQTT) | new transport adapter + tool family |
| Multiple Android devices | `devices` table + dispatcher fan-out (per-device queues) | already modeled; UI for device pick |
| Multiple PCs | laptops each run AgentCore; shared DB via Postgres adapter + broker | database/vector swap |
| Local LLM | `llm/providers/ollama_provider.py` | one provider class |
| Cloud deployment | containerize AgentCore; Postgres + object storage + broker | infra + DB adapter |
| Plugin system | `plugins/` loader registering tools + memory hooks | stable tool/event APIs |

**The rule:** every capability is either a *tool* (action), a *provider* (reasoning), a *transport* (device link), or a *store* (memory). New features pick a seam; the core loop never changes.

---

## 14. Recommended Implementation Order (before writing code)

1. **Lock the contracts first** — define `LLMMessage`, `LLMResponse`, `ToolSpec`, the envelope, and the memory API as Pydantic schemas. Everything else implements against these.
2. **Phase 0–1 (this is the first sprint):** skeleton + config + logging + SQLite + one provider + `LLM.chat()` + agent loop + 3 local tools. This proves the core loop before any Android work.
3. **Then deepen memory (Phase 2–3)** so recovery/continuity is real before adding a second device.
4. **Then the phone (Phase 5)** — the dispatcher + companion app against the already-stable protocol.

> Note: this document is a design. No application code has been written for AgentCore yet — the next step is to start Phase 0 with your go-ahead.

---

## 15. Reviewer-Critique Integration (every point → design response)

| Reviewer critique | Where it's handled |
|---|---|
| Routing is becoming a giant `if/elif` rule engine | §2.1 event-driven orchestrator + §2.5 Task Planner + §2.4 tool-registry *search*. The LLM proposes tool calls; the registry executes. No keyword chains anywhere. |
| No planner / "Goal → Planner → Tasks" missing | §2.5 Task Planner; §6 `plans` + `plan_steps` (DAG, statuses, attempts); §3.3 crash-resume. |
| Memory: JSON fine for 20 items, not 20,000 | §6 SQLite (WAL) for everything; §16 migration path for existing `todos.json`/`habits.json`/`expenses.json`. |
| No persistent conversation (system+user = chatbot) | §2.2 canonical path: Conversation → SQLite → retrieve → summarize → build prompt → LLM. |
| API abstraction (agents should never know the provider) | §8 `LLM.chat()` facade + `BaseProvider`; §8.3 rotation/failover with context replay. `CodingAgent` never knows who answered. |
| Too much logic in orchestrator (SRP) | §2.1 + §15 above: logic pushed to tools/devices/planner; orchestrator coordinates via events. |
| Missing task system (Task → Subtasks → Current step → Failure → Resume) | §2.5 + §6 `plan_steps` + `working_memory` + recovery. |
| Missing tool registry (50 tools shouldn't be hardcoded) | §2.4 registry + `search()` + `describe()` + capability routing — MCP-like. |
| Android prep (Device Manager → Windows/Android/Linux/Cloud) | §2.6 `device.execute(...)`; §5 `devices/`; §13 multi-device/multi-PC. |
| Security: `.env` must never be committed | §2.8 secrets in OS keyring; `.gitignore` (added to the JARVIS project already); §16 keeps `.env` local. |
| Dashboard must not call agents directly | §5 `api/` + `ui/`; `Dashboard → REST/WebSocket → Backend → Agent` (see §3.2). |
| Folder structure (`core/{planner,memory,llm,tasks,events,devices,tools}` …) | §5 flat equivalent: `agent/ memory/ llm/ planner/ tools/ devices/ events/ database/ config/ logs/ api/ ui/ plugins/`. |
| "The LLM isn't the center — the **task loop** is" | §2.1 loop + event bus + planner: Goal → Planner → Task Queue → Tool → Observation → Memory → Reflection → Next Step → Repeat. |

**Bottom line:** the reviewer's recommended future architecture and this design converge. The prototype is not a dead end — see §16 for exactly what carries over.

---

## 16. JARVIS Prototype → AgentCore Migration Path

The critique says: *keep the organization/modularity, replace the core orchestration model.* Concretely:

### What carries over (retain, repackage)

| JARVIS piece | Becomes |
|---|---|
| `agents/` (CodingAgent, LifeOS, StudyGuru) | **Capability handlers / plugins** — domain logic stays, wired through the tool registry + planner instead of keyword routing |
| `tools/` (voice, music, coding, file_manager) | **Tool Registry entries** — each becomes `{name, description, schema, execute}` |
| `dashboard/` templates | Served by `api/` (FastAPI) as static UI; **never calls agents directly** |
| `config.py` + `.env` | Config Manager; secrets move to OS keyring (Windows DPAPI) |
| `main.py` CLI | Thin wrapper over the agent loop |
| Voice config / 2-voice alias logic | `devices/` + a `voice` tool family — alias detection stays, but as a tool, not orchestrator branches |

### What gets replaced (the core)

| JARVIS pattern | AgentCore replacement |
|---|---|
| `JarvisOrchestrator.route()` — if/elif keyword chains (youtube, todo, study, …) | Event bus + planner + task loop; tools discovered via registry search |
| `BaseAgent` owning the OpenAI client | `llm/` LLM Manager + `BaseProvider` classes + router (key rotation, failover, context replay) |
| `todos.json` / `habits.json` / `expenses.json` | SQLite tables (`todos`, `habits`, `expenses`) — one-time migration script |
| No task state | `plans` + `plan_steps` + `working_memory` with checkpoint/resume |
| No device concept | `devices/` — WindowsDevice first, AndroidDevice after |
| Synchronous request→response | Event-driven loop with persistence |

### Migration order (each step is independently shippable)

1. **Extract logic out of the orchestrator** — move voice/music/config/file handling into standalone tool modules (pure refactor, zero behavior change, easy to test).
2. **Introduce the event bus + agent loop** — orchestrator becomes a subscriber; UI/CLI talk to the loop.
3. **SQLite migration** — copy JSON data into tables (schema from §6); keep JSON readers as a shim until nothing reads them.
4. **LLM Service** — pull the client out of `BaseAgent`; add provider classes + router.
5. **Planner + task objects** — replace routing with plan decomposition; add resume.
6. **Device Manager** — wrap local tools as `WindowsDevice`, then add `AndroidDevice` + companion app (existing §9 design).

> This is exactly the "freeze feature development, restructure the foundation" recommendation — but sequenced so JARVIS keeps working after each step, never a big-bang rewrite.
