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

    def __init__(self, config) -> None:
        self.voice = config.get_str("voice.tts_voice", "en-US-ChristopherNeural")

    def health(self) -> dict:
        try:
            import edge_tts  # noqa: F401
        except Exception:  # noqa: BLE001
            return {"name": self.name, "state": "MISSING",
                    "detail": "edge-tts not installed",
                    "fix": "pip install edge-tts"}
        return {"name": self.name, "state": "READY",
                "detail": f"edge voice {self.voice}", "fix": ""}

    async def _synthesize(self, text: str) -> bytes:
        import edge_tts
        communicate = edge_tts.Communicate(text, self.voice)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()

    def synthesize(self, text: str) -> tuple[str, bytes]:
        data = asyncio.run(self._synthesize(text))
        if not data:
            raise RuntimeError("edge-tts returned no audio (network? voice name?)")
        return ("mp3", data)
