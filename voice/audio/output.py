"""AgentCore — voice/audio/output.py
Speaker playback for TTS audio.

Primary: miniaudio (bundled mp3/wav decoders + PlaybackDevice). If no audio
output device exists (headless/SSH) the audio is saved to the tts_cache and
the caller is told — never silently dropped.
"""
from __future__ import annotations

import time
from pathlib import Path


class Speaker:
    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def available() -> bool:
        try:
            import miniaudio  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    def play(self, data: bytes, fmt: str = "mp3") -> dict:
        """Play audio bytes. Returns {'played': True} or an honest
        {'played': False, 'saved_to': path, 'error': ...}."""
        if not data:
            return {"played": False, "error": "no audio data"}
        try:
            import miniaudio
            decoded = miniaudio.decode(
                data, output_format=miniaudio.SampleFormat.SIGNED16)
            samples = bytes(decoded.samples)
            byte_width = decoded.sample_width * decoded.nchannels
            total = len(samples)

            def gen():
                pos = 0
                while True:
                    framecount = yield b""
                    need = framecount * byte_width
                    chunk = samples[pos:pos + need]
                    pos += len(chunk)
                    if len(chunk) < need:          # pad the final chunk
                        chunk += b"\x00" * (need - len(chunk))
                        yield chunk
                        return
                    yield chunk
                    if pos >= total:
                        return

            device = miniaudio.PlaybackDevice(
                output_format=miniaudio.SampleFormat.SIGNED16,
                nchannels=decoded.nchannels, sample_rate=decoded.sample_rate)
            t0 = time.time()
            gen_fn = gen()
            next(gen_fn)          # prime — miniaudio sends framecount via send()
            device.start(gen_fn)
            # miniaudio playback is async; block ~the audio duration so the
            # speak→listen sequence stays sequential (generator StopIteration
            # stops the feed, then we close the device).
            import time as _t
            duration_s = total / (decoded.sample_rate * byte_width)
            _t.sleep(max(duration_s, 0.05))
            device.stop()
            device.close()
            return {"played": True, "duration_s": round(duration_s, 2)}
        except Exception as e:  # noqa: BLE001 — no audio device / decode issue
            path = self.cache_dir / f"speech_{int(time.time()*1000)}.{fmt}"
            path.write_bytes(data)
            return {"played": False, "saved_to": str(path),
                    "error": f"playback unavailable: {str(e)[:120]}"}

    def play_file(self, path: str) -> dict:
        return self.play(Path(path).read_bytes(),
                         Path(path).suffix.lstrip(".") or "wav")
