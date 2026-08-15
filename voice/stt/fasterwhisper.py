"""AgentCore — voice/stt/fasterwhisper.py
Offline speech-to-text with faster-whisper (CTranslate2). FREE, no API key,
no account balance — the model auto-downloads from Hugging Face on first use
(cache: ~/.cache/huggingface). Best default for a personal agent that must
"just work".

Reports MISSING honestly when the package is absent; UNAVAILABLE when the
model cannot be loaded. Never fabricates a transcript.
"""
from __future__ import annotations

import structlog

from . import SttProvider

log = structlog.get_logger("agentcore.voice.stt.fasterwhisper")

_DEFAULT_MODEL = "base.en"   # tiny.en faster / small.en more accurate


class FasterWhisperStt(SttProvider):
    name = "fasterwhisper"

    def __init__(self, config) -> None:
        self.cfg = config
        self.model_name = config.get_str("voice.whisper_model", _DEFAULT_MODEL)

    def health(self) -> dict:
        try:
            import faster_whisper  # noqa: F401
        except Exception:  # noqa: BLE001
            return {"name": self.name, "state": "MISSING",
                    "detail": "faster-whisper not installed",
                    "fix": "pip install faster-whisper"}
        return {"name": self.name, "state": "READY",
                "detail": f"offline model {self.model_name} "
                          "(auto-downloads on first use)", "fix": ""}

    def transcribe(self, audio_path: str) -> str:
        from faster_whisper import WhisperModel
        try:
            model = WhisperModel(self.model_name, device="cpu",
                                 compute_type="int8")
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"faster-whisper model load failed: {e}") from e
        segments, info = model.transcribe(audio_path, language="en",
                                          beam_size=5, vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        log.info("stt transcribed (fasterwhisper)", model=self.model_name,
                 language=getattr(info, "language", ""), chars=len(text))
        return text
