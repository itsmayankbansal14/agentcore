"""AgentCore — voice/stt/vosk_local.py
Offline speech-to-text with Vosk (optional). No network, no API key — but it
needs the vosk package AND a downloaded model (config `voice.vosk_model_path`).

Reports UNAVAILABLE honestly when the package/model is missing; it never
pretends to transcribe.
"""
from __future__ import annotations

import json
import shutil
import wave

import structlog

from . import SttProvider

log = structlog.get_logger("agentcore.voice.stt.vosk")


class VoskStt(SttProvider):
    name = "vosk"

    def __init__(self, config) -> None:
        self.cfg = config
        self.model_path = config.get_str("voice.vosk_model_path",
                                         "data/voice/vosk-model")

    def _model_dir(self) -> str:
        import os
        from pathlib import Path
        p = Path(self.model_path)
        if not p.is_absolute():
            p = Path(os.getcwd()) / p
        return str(p)

    def health(self) -> dict:
        try:
            import vosk  # noqa: F401
        except Exception:  # noqa: BLE001
            return {"name": self.name, "state": "MISSING",
                    "detail": "vosk not installed",
                    "fix": "pip install vosk (optional offline STT)"}
        if not self._model_exists():
            return {"name": self.name, "state": "MISSING",
                    "detail": f"vosk model not found at {self.model_path}",
                    "fix": "download a model from vosk models and set "
                           "voice.vosk_model_path in config"}
        return {"name": self.name, "state": "READY",
                "detail": f"offline model {self.model_path}", "fix": ""}

    def _model_exists(self) -> bool:
        """A real vosk model contains am/final.mdl (acoustic model)."""
        from pathlib import Path
        d = Path(self._model_dir())
        return (d.is_dir() and (d / "am" / "final.mdl").exists())

    def transcribe(self, audio_path: str) -> str:
        from vosk import KaldiRecognizer, Model

        if not self._model_exists():
            raise RuntimeError(
                f"vosk model not found at {self.model_path} — download one and "
                "set voice.vosk_model_path (optional offline STT)")
        model = Model(self._model_dir())
        rec = KaldiRecognizer(model, 16000)
        with wave.open(audio_path, "rb") as wf:
            if wf.getframerate() != 16000:
                raise RuntimeError("vosk requires 16 kHz audio input")
            parts: list[str] = []
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                if rec.AcceptWaveform(data):
                    parts.append(json.loads(rec.Result()).get("text", ""))
        parts.append(json.loads(rec.FinalResult()).get("text", ""))
        text = " ".join(p for p in parts if p).strip()
        log.info("stt transcribed (vosk)", chars=len(text))
        return text
