"""AgentCore — voice/wake/base.py
WakeDetector seam + the honest disabled implementation.

Product direction: do NOT implement wake word / continuous listening until
the basic speak→hear pipeline is reliable. DisabledWakeDetector is the
default: it never triggers and reports UNAVAILABLE — no fake wake detection.
"""
from __future__ import annotations


class WakeDetector:
    name = "base"

    def detect(self, audio_path: str | None = None) -> bool:
        raise NotImplementedError

    def health(self) -> dict:
        return {"name": self.name, "state": "BROKEN",
                "detail": "not implemented", "fix": ""}


class DisabledWakeDetector(WakeDetector):
    name = "disabled"

    def detect(self, audio_path: str | None = None) -> bool:
        return False

    def health(self) -> dict:
        return {"name": self.name, "state": "UNAVAILABLE",
                "detail": "wake word deferred (voice MVP: manual start)",
                "fix": ""}


def build_wake_detector(config) -> WakeDetector:
    if config.get_bool("voice.wake_word_enabled", False):
        # future real detectors plug in here (e.g. openWakeWord/porcupine)
        from .base import DisabledWakeDetector
        return DisabledWakeDetector()
    from .base import DisabledWakeDetector
    return DisabledWakeDetector()
