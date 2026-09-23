# AgentCore

**Personal AI agent for Windows with Android control via voice.**

Talk naturally to your computer. AgentCore listens, understands, executes, verifies, responds, and keeps listening. Control your Windows machine and Android devices through conversation.

---

## Current Status

**Architecture: IMPLEMENTED ✅**  
**Hardware Validation: UNVERIFIED ❌**

All components exist and implement the specification correctly. Three critical bugs were fixed on 2026-09-17. The system has NOT been tested on real hardware yet.

### What Works (on paper)
- Voice input (faster-whisper STT with multilingual support)
- Natural language understanding
- Windows automation (browser, applications)
- Android control via ADB
- Observer-based verification (proves actions actually happened)
- Text-to-speech responses (edge-tts)
- Persistent voice loop (continues listening after each interaction)
- Native Windows executable packaging

### What's Unverified
- Real microphone has NOT captured audio
- Real STT has NOT transcribed speech
- Real browser has NOT been automated
- Real Android device has NOT been controlled
- Real TTS has NOT played audio
- Real AgentCore.exe has NOT launched
- Persistent loop has NOT been tested beyond first interaction

"Implemented" ≠ "verified." The architecture is sound. The real test starts now.

---

## Bugs Fixed (2026-09-17)

### 1. Critical: Multilingual STT Configuration
**Problem:** `config/defaults.yaml` hardcoded English-only model (`base.en`) despite code supporting multilingual detection.

**Fixed:** Config now declares `stt_language: auto` with automatic model selection:
- `auto` → multilingual base model
- `en` → English-only base.en model
- `hi` → Hindi support enabled

**Impact:** Unblocked Hindi and automatic language detection.

### 2. Code Quality: Duplicate TTS Method
**Problem:** `voice/tts/edge.py` defined `synthesize_async()` twice.

**Fixed:** Removed duplicate definition, single clean implementation remains.

**Impact:** Cleaner code, no silent override behavior.

### 3. Safety: Voice Thread Cleanup
**Problem:** `launcher.py` VoiceRuntimeThread initialized `self.loop` inside try block. If imports failed, cleanup could crash with AttributeError.

**Fixed:** Initialize `self.loop = None` in `__init__` before any try block.

**Impact:** Guaranteed safe cleanup even during startup failures.

---

## Quick Start

**Prerequisites:**
- Windows 10/11
- Python 3.12 ONLY (NOT 3.11, NOT 3.13+)
- Microphone and speakers
- Internet connection (first run downloads STT model)

**Run this:**
```batch
cd C:\Users\Mayank Bansal\Documents\agentcore
python bootstrap.py
python main.py voice --loop
```

Then speak: "What time is it?"

If that works, the core pipeline is proven. If it doesn't, nothing else matters until it does.

---

## Documentation

Comprehensive documentation created 2026-09-17:

- **[STATUS.md](STATUS.md)** — Current implementation status, bugs fixed, what's verified vs unverified
- **[VALIDATION.md](VALIDATION.md)** — Step-by-step hardware validation procedures with expected outputs
- **[CHANGES.md](CHANGES.md)** — Complete changelog of bug fixes and documentation created

Start with STATUS.md to understand where the project stands. Use VALIDATION.md when you're ready to test on real hardware.

---

## Acceptance Criteria (Unverified)

These workflows are implemented but NOT validated on real hardware:

| Workflow | Code Exists | Hardware Tested |
|----------|-------------|-----------------|
| Voice → "What time is it?" → TimeTool → TTS → Listen again | ✅ | ❌ |
| Voice → "Open YouTube" → Windows Browser → Verification → TTS | ✅ | ❌ |
| Voice → "Open YouTube on my phone" → Android ADB → Verification → TTS | ✅ | ❌ |
| Voice → "Save this website" → Personal Memory → Briefing | ✅ | ❌ |
| AgentCore.exe → Native Windows Launch → Voice Runtime | ✅ | ❌ |
| Persistent Voice Loop (continues after first interaction) | ✅ | ❌ |

Current validation: **0/13 test steps completed** (see STATUS.md for full checklist).

---

## Architecture Principles

What makes AgentCore different from typical voice assistants:

- **Planner ≠ Executor** — Planning and execution are separate phases
- **Tool Success ≠ Task Success** — Observer verifies actual outcomes, not just API responses
- **Target Resolution** — Explicit separation of requested device vs actual execution device
- **Voice is Interface** — Normalized input path shared with chat (voice is not special)
- **Shared AgentApp** — Dashboard and voice use same runtime instance
- **Async-First Voice** — Core is async, sync wrappers only at boundaries
- **No Nested asyncio.run()** — Voice thread owns its own event loop

---

## For Personal Use Only

This is a personal project for individual productivity. It is NOT designed for:
- Public distribution
- Multi-user environments
- Production deployment
- Commercial use
- Untrusted environments

AgentCore executes commands on your Windows machine and Android devices. Use it only on hardware you control.

---

## What Success Looks Like

From the handoff specification:

> "AgentCore is not successful because it has a sophisticated architecture.
>
> AgentCore is successful when I can actually sit at my Windows machine and say:
> 'What time is it?' and it answers.
>
> Then: 'Open YouTube.' and it actually opens YouTube, verifies it, speaks back, and listens again.
>
> That is the standard. Everything else is secondary."

**Current Reality:**
- Architecture: ✅ Sophisticated and correct
- "What time is it?" on real hardware: ❌ UNVERIFIED
- "Open YouTube" on real hardware: ❌ UNVERIFIED

---

## Next Steps

### Phase 0: Environment Check
```batch
python --version          # Must be 3.12.x ONLY
python bootstrap.py       # Install dependencies
python main.py doctor     # Health check
```

### Phase 1: First Voice Interaction (CRITICAL)
```batch
python main.py voice --loop
```

Speak: "What time is it?"

Expected: Transcription → Agent responds with time → Audio plays → Continues listening

**This is the fundamental proof.** If this works, the pipeline is real. If it doesn't, everything else is theoretical.

### Phase 2: Windows Automation
Speak: "Open YouTube"

Expected: Browser launches → YouTube loads → Observer verifies → TTS confirms → Continues listening

### Phase 3: Native Executable
```batch
build_exe.bat
dist\AgentCore.exe
```

Expected: EXE launches → Voice works identically to Python runtime

### Phase 4: Android Control
Prerequisites: Android phone with USB debugging enabled, ADB installed

Speak: "Open YouTube on my phone"

Expected: ADB executes → YouTube opens on phone → Screenshot captured → Verification succeeds → TTS confirms

---

## Troubleshooting

**Environment issues:** Check [VALIDATION.md](VALIDATION.md) Phase 0 troubleshooting.

**Voice not working:** Check [VALIDATION.md](VALIDATION.md) Phase 1 for microphone, STT, and TTS debugging.

**Browser automation failing:** Check [VALIDATION.md](VALIDATION.md) Phase 2 for Playwright and observer issues.

**Android not connecting:** Check [VALIDATION.md](VALIDATION.md) Phase 4 for USB debugging and ADB setup.

---

## Project Structure

```
agentcore/
├── config/             # Configuration (defaults.yaml)
├── core/              # Shared runtime, database, state
├── planning/          # Target resolver, planner
├── execution/         # Executor, tool registry
├── observer/          # Verification logic (browser, Android)
├── voice/             # Voice manager, STT, TTS
│   ├── stt/          # Speech-to-text (faster-whisper)
│   └── tts/          # Text-to-speech (edge-tts)
├── tools/             # Tool implementations
├── dashboard/         # Web UI (FastAPI)
├── launcher.py        # Native desktop runtime (AgentCore.exe)
├── main.py           # CLI entry point
├── bootstrap.py      # Environment setup
├── build_exe.bat     # Native EXE build pipeline
├── STATUS.md         # Current project status
├── VALIDATION.md     # Hardware validation guide
└── CHANGES.md        # Changelog
```

---

## Technical Requirements

### Required
- Windows 10 or 11
- Python 3.12.x ONLY (NOT 3.11, NOT 3.13+)
- 2GB RAM minimum (4GB recommended for STT model)
- Microphone (USB or built-in)
- Speakers or headphones
- Internet connection (initial STT model download, TTS synthesis)

### Optional
- Android device with USB debugging (for Android control)
- ADB (Android Debug Bridge) in PATH
- Git (for version control)

### Python Dependencies
Installed automatically via `bootstrap.py`:
- faster-whisper (offline STT)
- edge-tts (online TTS)
- playwright (browser automation)
- adb-shell (Android control)
- anthropic (Claude API)
- fastapi (dashboard)
- sounddevice (audio I/O)
- miniaudio (audio playback)

---

## Development Status

**Last Updated:** 2026-09-17 08:55 UTC

**Current Phase:** Ready for hardware validation

**Next Milestone:** Complete Phase 1 voice interaction on real hardware

**Known Issues:** None (bugs fixed, configuration consistent)

**Blockers:** None (all dependencies available, architecture complete)

---

## License

Personal project. Not licensed for redistribution or commercial use.

---

## Acknowledgments

Built with Claude Sonnet 4 as development partner.

Architecture follows principles from:
- ReAct pattern (reasoning + acting)
- Observer pattern (verification-based outcomes)
- Async-first design (avoiding blocking operations)

---

**Ready to validate?** Start with `python main.py doctor` and follow [VALIDATION.md](VALIDATION.md).

**Questions about status?** Read [STATUS.md](STATUS.md) for implementation details.

**Want to see what changed?** Check [CHANGES.md](CHANGES.md) for the complete audit log.

The code is ready. The hardware test begins now.
