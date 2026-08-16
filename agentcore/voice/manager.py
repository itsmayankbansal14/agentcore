"""AgentCore — voice/manager.py
VoiceManager — the primary interface orchestration:

    listen (audio.input) → STT → transcript
        → orchestrator.handle_user_message (SAME normalized input as chat)
        → response → TTS → speaker
        → transcript + response also land in the chat transcript

The agent runtime (Planner/Executor/etc.) has ZERO dependency on this module;
the manager only calls the public orchestrator API. Providers are injected
seams so tests can drive the full pipeline without a microphone.
"""
from __future__ import annotations

import asyncio
import sys
import threading

import structlog

log = structlog.get_logger("agentcore.voice")


class VoiceManager:
    def __init__(self, app, *, stt=None, tts=None, source=None, speaker=None,
                 wake=None, config=None) -> None:
        self.app = app
        self.cfg = config or app.config
        self.session_id = self.cfg.get_str("voice.session_id", "voice")
        from .audio.input import MicrophoneSource
        from .audio.output import Speaker
        from .stt import build_stt
        from .tts import build_tts
        from .wake.base import build_wake_detector
        self.stt = stt if stt is not None else build_stt(self.cfg)
        self.tts = tts if tts is not None else build_tts(self.cfg)
        self.source = source if source is not None else MicrophoneSource()
        self.speaker = speaker if speaker is not None else Speaker(
            self.app.workspace.tts_cache if getattr(self.app, "workspace", None)
            else self.app.config.data_dir)
        self.wake = wake if wake is not None else build_wake_detector(self.cfg)
        self.sample_rate = self.cfg.get_int("voice.sample_rate", 16000)
        self.silence_after_s = self.cfg.get_float("voice.silence_after_s", 1.2)
        self.max_record_s = self.cfg.get_float("voice.max_record_s", 15.0)
        self._stop_event = threading.Event()

        # Initialize STT model once at VoiceManager construction (Priority 2)
        try:
            if hasattr(self.stt, "initialize"):
                self.stt.initialize()
        except Exception:  # noqa: BLE001 — non-fatal; transcribe will retry
            pass

    # ------------------------------------------------------------------ health
    def health(self) -> dict:
        stt_h = self.stt.health()
        tts_h = self.tts.health()
        mic_ok = self.source.available() if hasattr(self.source, "available") else True
        spk_ok = self.speaker.available() if hasattr(self.speaker, "available") else True
        return {"stt": stt_h, "tts": tts_h,
                "microphone": {"state": "READY" if mic_ok else "UNAVAILABLE",
                               "detail": self.source.name if mic_ok
                               else "no input device"},
                "speaker": {"state": "READY" if spk_ok else "UNAVAILABLE",
                            "detail": "playback device" if spk_ok
                            else "no output device — audio saved instead"}}

    def stop(self) -> None:
        """Signal the persistent voice loop to stop."""
        self._stop_event.set()

    # ------------------------------------------------------------------ pipeline (async core)
    async def run_once_async(self, session_id: str | None = None) -> dict:
        """One full cycle (async): record → STT → agent → TTS → speak.
        Returns the transcript, response, and playback result.
        Core implementation — no asyncio.run() inside this class.

        Phase 2: Recoverable failures are caught, reported, and the loop continues.
        Only unrecoverable errors propagate out of the persistent runtime.
        """
        sid = session_id or self.session_id
        try:
            # 1) record
            print("🎤 listening…  (speak now)", flush=True)
            audio_path = self.source.record(
                sample_rate=self.sample_rate,
                silence_after_s=self.silence_after_s,
                max_duration_s=self.max_record_s)
            # 2) STT
            text = self.stt.transcribe(audio_path)
            if not text:
                print("  (no speech detected — try again)", flush=True)
                return {"transcript": "", "response": "", "played": False, "status": "no_speech"}
            print(f"🎤 You: {text}", flush=True)
            # 3) agent (same input path as chat)
            response = await self.app.orchestrator.handle_user_message(sid, text)
            print(f"🤖 {response}", flush=True)

            # 4) TTS → speak (use async path)
            fmt, data = await self.tts.synthesize_async(response)
            played = await asyncio.to_thread(self.speaker.play, data, fmt)
            if not played.get("played") and played.get("saved_to"):
                print(f"  🔊 (no audio device — saved to {played['saved_to']})",
                      flush=True)
            return {"transcript": text, "response": response, "played": played, "status": "ok"}

        except Exception as e:  # noqa: BLE001 — Phase 2: isolate recoverable failures
            print(f"  ⚠ Voice interaction failed: {e}", flush=True)
            return {"transcript": "", "response": "", "played": False, "status": "error", "error": str(e)[:200]}

    def run_once(self, session_id: str | None = None) -> dict:
        """Synchronous wrapper for CLI boundary only.
        
        NOTE: This uses asyncio.run() and should ONLY be called from
        non-async entry points (CLI commands, tests). Do not call from
        within an existing event loop. Core runtime uses run_once_async().
        """
        return asyncio.run(self.run_once_async(session_id))

    async def run_loop_async(self, session_id: str | None = None, wake: bool = False,
                             max_rounds: int | None = None) -> int:
        """Async repeat cycles until Ctrl+C (or max_rounds for tests).
        
        This is the PRIMARY method for persistent voice runtime.
        Caller must provide an event loop (e.g., VoiceRuntimeThread creates its own).
        """
        sid = session_id or self.session_id
        n = 0
        try:
            while (
                not self._stop_event.is_set()
                and (max_rounds is None or n < max_rounds)
            ):
                await self.run_once_async(sid)
                n += 1
        except KeyboardInterrupt:
            print("\n👋 voice session ended", flush=True)
        return n

    def run_loop(self, session_id: str | None = None, wake: bool = False,
                 max_rounds: int | None = None) -> int:
        """Synchronous wrapper for CLI boundary only.
        
        NOTE: This uses asyncio.run() and should ONLY be called from
        non-async entry points (CLI commands, tests). Do not call from
        within an existing event loop. Core runtime uses run_loop_async()
        with a dedicated event loop (see VoiceRuntimeThread).
        """
        return asyncio.run(self.run_loop_async(session_id, wake, max_rounds))


def build_voice(app) -> VoiceManager:
    """Build the VoiceManager over a running AgentApp."""
    return VoiceManager(app)
