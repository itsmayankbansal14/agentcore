"""AgentCore — voice/audio/input.py
Audio sources for the voice pipeline.

  MicrophoneSource — records from the default input device (sounddevice /
                     PortAudio). REQUIRES a real audio device; raises a clear
                     error when none exists (headless/SSH).
  WavFileSource   — returns a pre-recorded WAV file (tests / offline replay).

Recording stops at end-of-speech (silence longer than `silence_after_s`)
or at `max_duration_s`, whichever comes first. A recording with no speech is
returned as-is and the caller decides (STT of silence → empty transcript).
"""
from __future__ import annotations

from pathlib import Path

from .vad import EnergyVAD, write_wav_pcm


class AudioSource:
    name = "base"

    def record(self, sample_rate: int = 16000, silence_after_s: float = 1.2,
               max_duration_s: float = 15.0,
               threshold_db: float = -35.0) -> str:
        raise NotImplementedError


class MicrophoneSource(AudioSource):
    name = "microphone"

    @staticmethod
    def available() -> bool:
        try:
            import sounddevice as sd  # noqa: F401
            sd.query_devices(kind="input")
            return True
        except Exception:  # noqa: BLE001 — no PortAudio / no input device
            return False

    def record(self, sample_rate: int = 16000, silence_after_s: float = 1.2,
               max_duration_s: float = 15.0,
               threshold_db: float = -35.0) -> str:
        if not self.available():
            raise RuntimeError(
                "no audio input device (PortAudio not found or no microphone). "
                "On Windows install/connect a microphone; the voice pipeline "
                "cannot record without one.")
        import numpy as np
        import sounddevice as sd

        vad = EnergyVAD(sample_rate=sample_rate, threshold_db=threshold_db)
        chunk_frames = vad.chunk
        max_frames = int(sample_rate * max_duration_s)
        pcm = bytearray()
        speech_seen = False
        silent_frames = 0
        silence_frames = int(sample_rate * silence_after_s)

        with sd.InputStream(samplerate=sample_rate, channels=1, dtype="int16",
                            blocksize=chunk_frames) as stream:
            while len(pcm) // 2 < max_frames:
                data, _overflowed = stream.read(chunk_frames)
                chunk = np.asarray(data, dtype="<i2").tobytes()
                pcm.extend(chunk)
                if vad.is_speech(chunk):
                    speech_seen = True
                    silent_frames = 0
                else:
                    silent_frames += chunk_frames
                    if speech_seen and silent_frames >= silence_frames:
                        break
        out = _tmp_wav("mic", bytes(pcm), sample_rate)
        return out


class WavFileSource(AudioSource):
    """Returns a pre-recorded WAV file instead of recording (tests/replay)."""

    name = "wavfile"

    def __init__(self, path: str) -> None:
        self.path = str(path)

    def record(self, sample_rate: int = 16000, silence_after_s: float = 1.2,
               max_duration_s: float = 15.0,
               threshold_db: float = -35.0) -> str:
        return self.path


def _tmp_wav(tag: str, pcm: bytes, sample_rate: int) -> str:
    import tempfile
    fd, path = tempfile.mkstemp(prefix=f"agentcore_{tag}_", suffix=".wav")
    Path(path).write_bytes(b"")  # ensure exists
    import os
    os.close(fd)
    write_wav_pcm(path, pcm, sample_rate)
    return path
