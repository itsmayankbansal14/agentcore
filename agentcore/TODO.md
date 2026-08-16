# AgentCore Implementation TODO

## Phase 1: Fix Native Launcher Voice Runtime (P0)
- [ ] Modify `VoiceRuntimeThread.run()` to use dedicated asyncio event loop with `run_loop_async()`
- [ ] Remove `asyncio.run()` from `VoiceRuntimeThread` - use `loop.run_until_complete(voice.run_loop_async())`
- [ ] Test launcher voice startup with `--skip-boot`

## Phase 2: Make Normal Launch Voice-First (P0)
- [ ] Extract shared `start_runtime_and_voice(app, enable_voice)` function in `launcher.py`
- [ ] Modify `main.py` normal launch (no args, not FROZEN) to use shared startup
- [ ] Start runtime server thread + voice thread (same as launcher)
- [ ] Keep `python main.py serve` / `--dev` as explicit dev mode
- [ ] Keep `python main.py voice` as debug one-shot mode

## Phase 3: Fix Async Voice Properly (P0)
- [ ] Remove `asyncio.run()` from `VoiceManager.run_once()` and `run_loop()`
- [ ] Keep only async methods as primary: `run_once_async()`, `run_loop_async()`
- [ ] Sync wrappers only at CLI boundary (`main.py cmd_voice`)
- [ ] Update `VoiceRuntimeThread` to use async methods (already done in Phase 1)

## Phase 4: Fix STT Model/Language Mismatch (P1)
- [ ] Change `config/defaults.yaml`: `whisper_model: base` (multilingual, not `base.en`)
- [ ] Add `stt_language: auto` config option (already supported in fasterwhisper.py)
- [ ] Verify language parameter passed correctly to transcribe()

## Phase 5: Verify Persistent Voice (P0)
- [ ] Test real end-to-end: "What time is it?" → time tool → TTS
- [ ] Test second interaction: "Open YouTube." → browser workflow → TTS
- [ ] Verify loop continues listening after each response
- [ ] Mark UNVERIFIED if no real provider configured

## Phase 6: Windows Vertical Slice (P0)
- [ ] Voice → TargetResolver → Windows/browser capability → execution → observer → verification → TTS
- [ ] Integration test with real provider (or mark UNVERIFIED)

## Phase 7: Audit TargetResolver (P0)
- [ ] Verify four target-state semantics: requested, actual, session_preference, fallback
- [ ] Test: Android requested + unavailable → requested=android, actual=windows, fallback=windows, preference unchanged

## Phase 8: Native Executable Build (P1) - DEFERRED
- [ ] Run build_exe.bat on Windows with Python 3.11/3.12
- [ ] Test AgentCore.exe launches voice + dashboard
- [ ] Mark UNVERIFIED until tested on real Windows

## Phase 9: Startup Briefing (P2)
- [ ] Normal launch: briefing → voice starts listening (not dashboard)

## Phase 10: Stop Architecture Expansion (P0) - PROCESS
- [ ] Freeze feature development until voice vertical slice passes