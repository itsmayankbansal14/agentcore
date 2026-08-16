# Legacy Jarvis — Inspiration Reference

These 4 files are the **only preserved pieces** of the old JARVIS prototype
(deleted 2026-08-07). Keep them purely as **design inspiration** — they are
NOT used by AgentCore at runtime. Mine them for ideas, then extend AgentCore's
own UI instead of copying code (AgentCore's dashboard is `../dashboard.html`).

---

## liquid_jarvis.html — the flagship UI (most valuable to borrow from)

Ideas worth stealing:
- **Full-screen liquid animation**: `<canvas id="liquidCanvas">` + 4 metaballs
  with a goo SVG filter, radial gradients `hsla(260–300)`, wobble via
  `Math.sin(angle*3 + phase)` — the "jiggle when the mic hears you" effect.
- **Central orb** (tap to talk) with ripple rings + waveform bars.
- **Audio-reactive jiggle**: `audioVolume` from a Web Audio analyser
  (`getUserMedia` → `AnalyserNode` → `getByteFrequencyData`), with a
  *simulated* jiggle fallback when the analyser can't start (avoids double
  mic permission conflicts with SpeechRecognition).
- **Mic robustness fixes** (the hard-won lessons):
  - `continuous = true` + `interimResults = true`, accumulate final transcript
  - interim "Hearing: …" chip + a debug box (`Vol / Listening / MicOn`)
  - **default mic ON** via `localStorage.getItem('micToggle') !== 'false'`
  - never disable the mic button; clicking it auto-enables the toggle
- **Agentic music embeds**: parses `[YOUTUBE_EMBED:embed|search|query]` and
  `[SPOTIFY_EMBED:url|query]` tags out of the assistant reply into a music bar.
- **Brave/iframe fix**: `isSecureContext` detection + "open in new tab" button.
- Settings gear modal with toggles (mic / voice switching / response mode /
  liquid / debug), all also voice-controllable.

## voices.html — voice lab

- Voice cards with Play buttons hitting `/api/voices/<id>/sample`.
- Set Primary / Set Secondary / Set Dual buttons → `/api/voices/set_*`.
- Custom TTS test box → `/api/tts?text=&voice=`.
- **Idea for AgentCore**: a voice lab tab in the dashboard with the same
  card grid, wired to AgentCore's providers instead of the old gTTS samples.

## jarvis_ai.html — "command center" view

- Orb + agent panels (CodeBuddy / LifeOS / StudyGuru) left, chat center,
  systems right. A denser dashboard layout than the current AgentCore one.
- HTTPS/iframe warning banner with "Open in New Tab" + lock-icon instructions.
- Voice identity cards (JARVIS = mentor, FRIDAY = friendly).

## index.html — original dashboard

- The **Voice Control Center** tab with 3 big toggle cards
  (Microphone / Voice Changing / Response Mode), each with status dots +
  the voice commands that control them ("mic on", "disable voice changing",
  "text only mode").
- Quick-command buttons + a "Get Morning Briefing" button.
- Config tab showing masked `.env`.

---

## The dual-voice concept (JARVIS + FRIDAY) — worth keeping as a feature idea

The prototype settled on **2 aliases**: `jarvis` → mentor voice, `friday` →
assistant voice, triggered by saying the name. AgentCore currently routes by
tools/planner only. If you want the "say a name to switch persona" UX back,
it's a small feature: add a `persona` field to the session and a tool that
sets it — the observer/executor architecture already supports it.

## What NOT to revive

- The `route()` if/elif keyword chains (replaced by planner + tool registry).
- JSON-file storage (now SQLite).
- gTTS-only voices (AgentCore uses provider TTS; edge-tts/mock for dev).
- The old orchestrator's mixed responsibilities (now separated: orchestrator /
  executor / planner / observer / reasoner).
