"""AgentCore — voice.stt
Speech-to-text providers. Each provider is REAL (a real model/API), reports
its own health honestly, and never fabricates a transcript.

Priority order (config `voice.stt_provider`):
  fasterwhisper — offline Whisper (free, no key, no balance; DEFAULT)
  openrouter    — Whisper via the OpenRouter API (same key as the LLM;
                  requires OpenRouter audio balance)
  vosk          — offline lightweight model (optional)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from config.manager import ConfigManager


class SttProvider:
    name = "base"

    def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError

    def health(self) -> dict:
        return {"name": self.name, "state": "BROKEN",
                "detail": "not implemented", "fix": ""}


def build_stt(config: "ConfigManager") -> SttProvider:
    """First HEALTHY provider wins (fasterwhisper → openrouter → vosk). If
    none is usable the first is returned anyway so `transcribe()` raises a
    clear error at use."""
    from .fasterwhisper import FasterWhisperStt
    from .openrouter import OpenRouterStt
    from .vosk_local import VoskStt

    order = {
        "fasterwhisper": [FasterWhisperStt(config), OpenRouterStt(config),
                          VoskStt(config)],
        "openrouter": [OpenRouterStt(config), FasterWhisperStt(config),
                       VoskStt(config)],
        "vosk": [VoskStt(config), FasterWhisperStt(config), OpenRouterStt(config)],
    }
    preferred = (config.get_str("voice.stt_provider", "fasterwhisper")
                 or "fasterwhisper").lower()
    providers = order.get(preferred, order["fasterwhisper"])
    for p in providers:
        if p.health().get("state") == "READY":
            return p
    return providers[0]
