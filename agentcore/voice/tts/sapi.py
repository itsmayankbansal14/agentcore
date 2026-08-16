"""AgentCore — voice/tts/sapi.py
Offline TTS via Windows SAPI5 (pyttsx3). Works without network on Windows.
Reports UNAVAILABLE honestly when no speech engine is present (headless).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import structlog

from . import TtsProvider

log = structlog.get_logger("agentcore.voice.tts.sapi")


class SapiTts(TtsProvider):
    name = "sapi"

    def __init__(self, config) -> None:
        self._engine = None
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
        except Exception as e:  # noqa: BLE001
            log.debug("pyttsx3 unavailable", error=str(e)[:100])
            self._engine = None

    def health(self) -> dict:
        if self._engine is None:
            return {"name": self.name, "state": "UNAVAILABLE",
                    "detail": "no speech engine (pyttsx3 init failed)",
                    "fix": "on Windows this uses SAPI5 automatically; "
                           "on Linux install espeak"}
        return {"name": self.name, "state": "READY",
                "detail": "windows SAPI5 (offline)", "fix": ""}

    def synthesize(self, text: str) -> tuple[str, bytes]:
        if self._engine is None:
            raise RuntimeError("pyttsx3 engine unavailable — cannot synthesize")
        fd, path = tempfile.mkstemp(prefix="agentcore_sapi_", suffix=".wav")
        os.close(fd)
        try:
            self._engine.save_to_file(text, path)
            self._engine.runAndWait()
            data = Path(path).read_bytes()
            if not data:
                raise RuntimeError("pyttsx3 produced no audio")
            return ("wav", data)
        finally:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
