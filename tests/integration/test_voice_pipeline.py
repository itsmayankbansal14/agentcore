"""Integration: Voice subsystem (primary interface).

  audio.input/VAD  → real end-of-speech detection on synthetic audio
  VoiceManager     → full pipeline driven through provider seams (no mic
                     needed): WAV source → STT → orchestrator → TTS → speaker
  honest states    → headless/no-device paths degrade with clear errors
  LIVE (optional)  → edge-tts speech → faster-whisper transcription (skips
                     when the model/network is unavailable)
"""
from __future__ import annotations

import math
import struct
import wave

import pytest


# ---------------------------------------------------------------------------
# VAD (real DSP on synthetic audio)
# ---------------------------------------------------------------------------
def _tone_pcm(sample_rate: int, freq: float, seconds: float, amp: int = 8000) -> bytes:
    n = int(sample_rate * seconds)
    return b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * i / sample_rate)))
                    for i in range(n))


def _silence_pcm(sample_rate: int, seconds: float) -> bytes:
    return b"\x00\x00" * int(sample_rate * seconds)


@pytest.mark.unit
def test_vad_detects_speech_and_end_of_speech():
    from voice.audio.vad import EnergyVAD
    sr = 16000
    pcm = _silence_pcm(sr, 0.5) + _tone_pcm(sr, 440, 1.0) + _silence_pcm(sr, 1.0)
    vad = EnergyVAD(sample_rate=sr)
    r = vad.analyze(pcm, silence_after_s=1.0)
    assert r.speech_found is True
    assert r.samples_before_speech >= int(0.4 * sr)   # leading silence skipped
    # speech ≈ 1s (end detected at the trailing silence)
    assert 0.6 <= r.speech_seconds <= 1.4


@pytest.mark.unit
def test_vad_silence_is_no_speech():
    from voice.audio.vad import EnergyVAD
    r = EnergyVAD(sample_rate=16000).analyze(_silence_pcm(16000, 2.0), silence_after_s=1.0)
    assert r.speech_found is False


@pytest.mark.unit
def test_wav_roundtrip(tmp_path):
    from voice.audio.vad import write_wav_pcm
    p = tmp_path / "t.wav"
    write_wav_pcm(str(p), _tone_pcm(16000, 440, 0.5), 16000)
    with wave.open(str(p), "rb") as wf:
        assert wf.getframerate() == 16000 and wf.getnchannels() == 1
        assert wf.getnframes() == 8000


# ---------------------------------------------------------------------------
# VoiceManager full pipeline (hermetic seams — no hardware)
# ---------------------------------------------------------------------------
class _ScriptedStt:
    name = "scripted"

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = []

    def transcribe(self, audio_path: str) -> str:
        self.calls.append(audio_path)
        return self.text

    def health(self) -> dict:
        return {"name": self.name, "state": "READY", "detail": "", "fix": ""}


class _ScriptedTts:
    name = "scripted"

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls = []

    def synthesize(self, text: str) -> tuple[str, bytes]:
        self.calls.append(text)
        return ("wav", self.payload)

    def health(self) -> dict:
        return {"name": self.name, "state": "READY", "detail": "", "fix": ""}


class _CaptureSpeaker:
    name = "capture"

    def __init__(self) -> None:
        self.played: list[tuple[str, bytes]] = []

    def play(self, data: bytes, fmt: str = "wav") -> dict:
        self.played.append((fmt, data))
        return {"played": True, "duration_s": 0.1}

    @staticmethod
    def available() -> bool:
        return True


@pytest.fixture()
def spoken_wav(tmp_path):
    p = tmp_path / "utterance.wav"
    with wave.open(str(p), "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
        wf.writeframes(_tone_pcm(16000, 440, 1.0))
    return str(p)


@pytest.mark.integration
def test_voice_manager_full_pipeline(app, spoken_wav):
    from voice.audio.input import WavFileSource
    from voice.audio.output import Speaker
    from voice.manager import VoiceManager

    stt = _ScriptedStt("what time is it")
    tts = _ScriptedTts(b"\x00" * 100)
    spk = _CaptureSpeaker()
    vm = VoiceManager(app, source=WavFileSource(spoken_wav), stt=stt, tts=tts,
                      speaker=spk)
    res = vm.run_once("vtest")
    # STT got the file, agent processed the transcript (deterministic → time)
    assert stt.calls == [spoken_wav]
    assert res["transcript"] == "what time is it"
    assert "It is" in res["response"]
    # the RESPONSE went to TTS and then to the speaker
    assert tts.calls and res["response"] in tts.calls[0]
    assert spk.played and spk.played[0][0] == "wav"
    # the transcript is in the chat history too
    from database.models import Message
    with app.db.session() as s:
        roles = [m.role for m in s.query(Message).filter_by(session_id="vtest").all()]
    assert "user" in roles


@pytest.mark.integration
def test_voice_manager_empty_transcript_skips_agent(app, spoken_wav):
    from voice.audio.input import WavFileSource
    from voice.manager import VoiceManager
    stt = _ScriptedStt("")   # silence → no speech
    vm = VoiceManager(app, source=WavFileSource(spoken_wav), stt=stt,
                      tts=_ScriptedTts(b"x"))
    res = vm.run_once("v2")
    assert res["transcript"] == "" and res["response"] == ""


@pytest.mark.integration
def test_voice_health_honest_without_hardware(app):
    from voice.manager import VoiceManager
    vm = VoiceManager(app, stt=_ScriptedStt("x"), tts=_ScriptedTts(b"x"))
    h = vm.health()
    assert h["stt"]["state"] == "READY" and h["tts"]["state"] == "READY"
    assert h["microphone"]["state"] in ("READY", "UNAVAILABLE")
    assert h["speaker"]["state"] in ("READY", "UNAVAILABLE")


@pytest.mark.integration
def test_speaker_play_empty_is_honest(tmp_path):
    from voice.audio.output import Speaker
    sp = Speaker(tmp_path)
    r = sp.play(b"")
    assert r["played"] is False and "no audio data" in r["error"]


@pytest.mark.integration
def test_speaker_saves_when_playback_unavailable(tmp_path, monkeypatch):
    from voice.audio.output import Speaker
    sp = Speaker(tmp_path)
    r = sp.play(b"\x00" * 1024, "wav")
    if not r["played"]:
        assert r["saved_to"] and "error" in r  # honest save fallback


# ---------------------------------------------------------------------------
# LIVE: real speech → real STT (edge-tts + faster-whisper). Skips when the
# model/network is unavailable so the suite stays hermetic on clean machines.
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_live_edge_tts_synthesizes():
    from config.manager import get_config
    from voice.tts.edge import EdgeTts
    tts = EdgeTts(get_config())
    if tts.health().get("state") != "READY":
        pytest.skip("edge-tts unavailable")
    fmt, data = tts.synthesize("open youtube on my phone")
    assert fmt == "mp3" and len(data) > 1000


@pytest.mark.integration
def test_live_fasterwhisper_transcribes_real_speech():
    try:
        from voice.stt.fasterwhisper import FasterWhisperStt
    except Exception:  # noqa: BLE001
        pytest.skip("faster-whisper not installed")
    try:
        from config.manager import get_config
        from voice.tts.edge import EdgeTts
    except Exception:  # noqa: BLE001
        pytest.skip("tts deps unavailable")
    tts = EdgeTts(get_config())
    if tts.health().get("state") != "READY":
        pytest.skip("edge-tts unavailable")
    fmt, data = tts.synthesize("open youtube on my phone")
    import miniaudio, tempfile, wave, os
    decoded = miniaudio.decode(data, output_format=miniaudio.SampleFormat.SIGNED16)
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        with wave.open(path, "wb") as wf:
            wf.setnchannels(decoded.nchannels)
            wf.setsampwidth(2)
            wf.setframerate(decoded.sample_rate)
            wf.writeframes(decoded.samples)
        stt = FasterWhisperStt(get_config())
        try:
            text = stt.transcribe(path)
        except Exception as e:  # noqa: BLE001 — model download/network flake
            pytest.skip(f"faster-whisper unavailable: {e}")
        assert "youtube" in text.lower(), text
    finally:
        os.unlink(path)
