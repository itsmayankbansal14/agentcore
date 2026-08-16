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
        self._model = None  # cached model instance (loaded once)

    def initialize(self) -> None:
        """Load the Whisper model once (called at voice startup)."""
        if self._model is not None:
            return
        from faster_whisper import WhisperModel
        try:
            self._model = WhisperModel(self.model_name, device="cpu",
                                       compute_type="int8")
            log.info("faster-whisper model loaded once", model=self.model_name)
        except Exception as e:  # noqa: BLE001
            self._model = None
            raise RuntimeError(f"faster-whisper model load failed: {e}") from e

    def health(self) -> dict:
        try:
            import faster_whisper  # noqa: F401
        except Exception:  # noqa: BLE001
            return {"name": self.name, "state": "MISSING",
                    "detail": "faster-whisper not installed",
                    "fix": "pip install faster-whisper"}

        if self._model is None:
            return {"name": self.name, "state": "PACKAGE_READY",
                    "detail": f"package available, model not loaded yet ({self.model_name})",
                    "fix": ""}

        return {"name": self.name, "state": "READY",
                "detail": f"offline model {self.model_name} (loaded once at startup)",
                "fix": ""}

    def transcribe(self, audio_path: str) -> str:
        if self._model is None:
            self.initialize()
        if self._model is None:
            raise RuntimeError("faster-whisper model not available")

        lang = self.cfg.get_str("voice.stt_language", "auto")
        lang_param = None if str(lang).lower() == "auto" else lang

        segments, info = self._model.transcribe(
            audio_path,
            language=lang_param,
            beam_size=5,
            vad_filter=True
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        log.info("stt transcribed (fasterwhisper)", model=self.model_name,
                 language=getattr(info, "language", ""), chars=len(text))
        return text

    def shutdown(self) -> None:
        """Release model resources (optional)."""
        self._model = None
