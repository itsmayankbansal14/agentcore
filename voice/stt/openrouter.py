"""AgentCore — voice/stt/openrouter.py
Speech-to-text via the OpenRouter API (`/api/v1/audio/transcriptions`,
Whisper-class models). Uses the SAME OpenRouter key as the LLM — no extra
accounts or billing setup for a personal agent.
"""
from __future__ import annotations

import structlog

from . import SttProvider

log = structlog.get_logger("agentcore.voice.stt.openrouter")

_DEFAULT_MODEL = "openai/whisper-1"


class OpenRouterStt(SttProvider):
    name = "openrouter"

    def __init__(self, config) -> None:
        self.cfg = config
        self.base_url = config.get_str("llm.base_url.openrouter",
                                       "https://openrouter.ai/api/v1")
        self.model = config.get_str("voice.stt_model", _DEFAULT_MODEL)
        self.api_key = config.get_secret("OPENROUTER_API_KEY")

    def health(self) -> dict:
        if not self.api_key:
            return {"name": self.name, "state": "MISSING",
                    "detail": "no OPENROUTER_API_KEY configured",
                    "fix": "add OPENROUTER_API_KEY to .env"}
        return {"name": self.name, "state": "READY",
                "detail": f"whisper via openrouter ({self.model})", "fix": ""}

    def transcribe(self, audio_path: str) -> str:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY not configured — cannot transcribe")
        try:
            from openai import OpenAI
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"openai SDK unavailable: {e}") from e
        client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        with open(audio_path, "rb") as f:
            result = client.audio.transcriptions.create(model=self.model, file=f)
        text = (result.text or "").strip()
        log.info("stt transcribed", model=self.model, chars=len(text))
        return text
