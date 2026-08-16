"""AgentCore — voice/tts/edge.py
High-quality neural TTS via Microsoft Edge voices (edge-tts). Requires
network; produces MP3 bytes.
"""
from __future__ import annotations

import asyncio
import io

import structlog

from . import TtsProvider

log = structlog.get_logger("agentcore.voice.tts.edge")


class EdgeTts(TtsProvider):
    name = "edge"

    PERSONA_VOICES = {
        "jarvis": "en-GB-RyanNeural",
        "friday": "en-GB-SoniaNeural",
    }

    def __init__(self, config) -> None:
        # New persona system (preferred)
        active_persona = config.get_str("voice.active_persona", "jarvis").lower()
        if active_persona in self.PERSONA_VOICES:
            self.voice = self.PERSONA_VOICES[active_persona]
        else:
            # Fallback to legacy config or default
            self.voice = config.get_str("voice.tts_voice", "en-US-ChristopherNeural")

    def health(self) -> dict:
        try:
            import edge_tts  # noqa: F401
        except Exception:  # noqa: BLE001
            return {"name": self.name, "state": "MISSING",
                    "detail": "edge-tts not installed",
                    "fix": "pip install edge-tts"}

        # Basic package health only — does not guarantee output device or playback
        return {"name": self.name, "state": "PACKAGE_READY",
                "detail": f"edge voice {self.voice} (package available)",
                "fix": ""}

    async def _synthesize(self, text: str) -> bytes:
        import edge_tts
        communicate = edge_tts.Communicate(text, self.voice)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()

    async def synthesize_async(self, text: str) -> tuple[str, bytes]:
        data = await self._synthesize(text)
        if not data:
            raise RuntimeError("edge-tts returned no audio (network? voice name?)")
        return ("mp3", data)

    async def synthesize_async(self, text: str) -> tuple[str, bytes]:
        data = await self._synthesize(text)
        if not data:
            raise RuntimeError("edge-tts returned no audio (network? voice name?)")
        return ("mp3", data)

    def synthesize(self, text: str) -> tuple[str, bytes]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # Safe to use asyncio.run() only when no loop is running
            data = asyncio.run(self._synthesize(text))
            if not data:
                raise RuntimeError("edge-tts returned no audio (network? voice name?)")
            return ("mp3", data)
        raise RuntimeError(
            "EdgeTts.synthesize() cannot be called from a running event loop; "
            "use await synthesize_async()"
        )
