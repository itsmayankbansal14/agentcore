"""AgentCore — voice/audio/vad.py
Real end-of-speech detection (energy-based). Works on 16-bit PCM frames:

  * speech if a short window's RMS is above the threshold
  * end-of-speech when trailing silence exceeds `silence_after_s`

MVP-grade and deterministic — no ML weights, no false promises. On a real
microphone stream the same logic runs per-chunk during recording.
"""
from __future__ import annotations

import math
import wave
from dataclasses import dataclass


def _rms_db(frames: bytes) -> float:
    """RMS of 16-bit little-endian PCM in decibels (silence → -inf)."""
    if not frames:
        return -math.inf
    n = len(frames) // 2
    if n == 0:
        return -math.inf
    s = 0
    for i in range(n):
        sample = int.from_bytes(frames[i * 2:i * 2 + 2], "little", signed=True)
        s += sample * sample
    rms = math.sqrt(s / n)
    if rms <= 1e-9:
        return -math.inf
    return 20.0 * math.log10(rms)


@dataclass
class VadResult:
    speech_found: bool
    samples_before_speech: int      # frames of leading silence skipped
    samples_total: int
    speech_seconds: float


class EnergyVAD:
    """Detect speech/silence in 16-bit mono PCM. threshold_db ≈ -35 is good
    for a quiet room; raise it for noisy environments."""

    def __init__(self, sample_rate: int = 16000, threshold_db: float = -35.0,
                 chunk_ms: int = 30) -> None:
        self.sample_rate = sample_rate
        self.threshold_db = threshold_db
        self.chunk = max(1, int(sample_rate * chunk_ms / 1000))  # frames/chunk

    def chunk_energy(self, frames: bytes) -> float:
        return _rms_db(frames)

    def is_speech(self, frames: bytes) -> bool:
        return _rms_db(frames) >= self.threshold_db

    def trim_silence(self, pcm: bytes) -> tuple[bytes, int]:
        """Drop leading silence. Returns (trimmed_pcm, frames_skipped)."""
        n = len(pcm) // 2
        i = 0
        while i < n:
            chunk = pcm[i * 2:(i + self.chunk) * 2]
            if self.is_speech(chunk):
                break
            i += self.chunk
        return pcm[i * 2:], i

    def end_of_speech_index(self, pcm: bytes, silence_after_s: float) -> int:
        """Frame index where trailing silence begins (end of speech).
        Returns len(pcm) if speech never stops within the buffer."""
        silence_frames = int(self.sample_rate * silence_after_s)
        n = len(pcm) // 2
        if n == 0:
            return 0
        silent_run = 0
        end = n
        for i in range(0, n, self.chunk):
            chunk = pcm[i * 2:(i + self.chunk) * 2]
            if self.is_speech(chunk):
                silent_run = 0
                end = i + self.chunk
            else:
                silent_run += self.chunk
                if silent_run >= silence_frames:
                    break
        return min(end, n)

    def analyze(self, pcm: bytes, silence_after_s: float = 1.0) -> VadResult:
        trimmed, skipped = self.trim_silence(pcm)
        speech_found = len(trimmed) > 0
        end = self.end_of_speech_index(trimmed, silence_after_s) if speech_found else 0
        return VadResult(speech_found=speech_found, samples_before_speech=skipped,
                         samples_total=len(trimmed) // 2 + skipped,
                         speech_seconds=round(end / self.sample_rate, 2))


def read_wav_pcm(path: str) -> tuple[int, int, bytes]:
    """(sample_rate, channels, 16-bit PCM bytes) from a WAV file."""
    with wave.open(path, "rb") as wf:
        rate = wf.getframerate()
        channels = wf.getnchannels()
        data = wf.readframes(wf.getnframes())
    return rate, channels, data


def write_wav_pcm(path: str, pcm: bytes, sample_rate: int, channels: int = 1) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
