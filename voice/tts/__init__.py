"""AgentCore — voice.tts
Text-to-speech providers. Each is REAL and honest:

  edge — Microsoft Edge neural voices (edge-tts, high quality, needs network)
  sapi — Windows SAPI5 via pyttsx3 (offline fallback)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from config.manager import ConfigManager


class TtsProvider:
    name = "base"

    def synthesize(self, text: str) -> tuple[str, bytes]:
        """Return (format, audio bytes). format ∈ {'mp3','wav'}."""
        raise NotImplementedError

    def health(self) -> dict:
        return {"name": self.name, "state": "BROKEN",
                "detail": "not implemented", "fix": ""}


def build_tts(config: "ConfigManager") -> TtsProvider:
    """First HEALTHY provider wins (edge → sapi)."""
    from .edge import EdgeTts
    from .sapi import SapiTts

    preferred = (config.get_str("voice.tts_provider", "edge") or "edge").lower()
    providers: list[TtsProvider] = []
    if preferred == "sapi":
        providers = [SapiTts(config), EdgeTts(config)]
    else:
        providers = [EdgeTts(config), SapiTts(config)]
    for p in providers:
        if p.health().get("state") == "READY":
            return p
    return providers[0]
