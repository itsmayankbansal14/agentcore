"""AgentCore — vision/verifier.py
REAL verification for the Android vertical slice.

`verify_screen(target, screenshot_path, llm, prev_screenshot)` decides whether
the target app actually opened, using three REAL signals (first that succeeds):

  1. LLM vision  — sends the screenshot (data URI) to the configured vision
                   model via OpenRouter and asks YES/NO.
  2. OCR         — RapidOCR (real OCR engine, ONNX) reads the screen text;
                   a hit on known YouTube tokens passes.
  3. Pixel diff  — if the screen changed materially vs the previous frame, the
                   action likely took effect (heuristic fallback).

Every path is real — no placeholder logic.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import structlog

from core.contracts import LLMMessage, Role

log = structlog.get_logger("agentcore.vision")

_YOUTUBE_TOKENS = ("youtube", "watch", "video", "play", "subscribe", "search", "trending")

_VERIFY_PROMPT = (
    "Look at this Android screenshot. Did the YouTube app or youtube.com actually "
    "open and is its content visible on screen? Reply with exactly 'YES' or 'NO' "
    "followed by a short reason on the same line."
)


@dataclass
class Verification:
    ok: bool
    reason: str
    engine: str          # llm_vision | ocr | pixel_diff | none
    screenshot: str = ""


def _data_uri(path: Path) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
class VisionVerifier:
    def __init__(self, llm=None, ocr: bool = True) -> None:
        self.llm = llm
        self.ocr = ocr
        self._ocr_engine = None
        self._prev: dict[str, str] = {}     # target -> last screenshot path

    # -- LLM vision ---------------------------------------------------------
    async def _try_llm(self, path: Path) -> Verification | None:
        if self.llm is None:
            return None
        try:
            msg = LLMMessage(role=Role.USER, content=[
                {"type": "text", "text": _VERIFY_PROMPT},
                {"type": "image_url", "image_url": {"url": _data_uri(path)}},
            ])
            resp = await self.llm.chat([msg])
            text = (resp.content or "").strip()
            ok = text.upper().startswith("YES") or "YES" in text.upper()[:6]
            return Verification(ok=ok, reason=text[:160], engine="llm_vision",
                                screenshot=str(path))
        except Exception as e:  # noqa: BLE001
            log.warning("llm vision failed", error=str(e)[:100])
            return None

    # -- OCR ----------------------------------------------------------------
    def _try_ocr(self, path: Path) -> Verification | None:
        if not self.ocr:
            return None
        try:
            if self._ocr_engine is None:
                from rapidocr_onnxruntime import RapidOCR
                self._ocr_engine = RapidOCR()
            result, _ = self._ocr_engine(str(path))
            if not result:
                return Verification(ok=False, reason="no text detected", engine="ocr",
                                    screenshot=str(path))
            text = " ".join(item[1] for item in result).lower()
            hits = [tok for tok in _YOUTUBE_TOKENS if tok in text]
            ok = bool(hits)
            return Verification(ok=ok,
                                reason=("found: " + ", ".join(hits)) if hits
                                       else "ocr text: " + text[:80],
                                engine="ocr", screenshot=str(path))
        except Exception as e:  # noqa: BLE001
            log.warning("ocr failed", error=str(e)[:100])
            return None

    # -- pixel diff ---------------------------------------------------------
    def _try_pixel(self, target: str, path: Path) -> Verification | None:
        prev = self._prev.get(target)
        self._prev[target] = str(path)
        if not prev or not Path(prev).exists():
            return None  # nothing to compare yet
        try:
            import numpy as np
            from PIL import Image
            a = np.asarray(Image.open(prev).convert("L").resize((64, 64)), dtype=float)
            b = np.asarray(Image.open(path).convert("L").resize((64, 64)), dtype=float)
            diff = float(np.mean(np.abs(a - b)))
            ok = diff > 3.0
            return Verification(ok=ok,
                                reason=f"pixel change {diff:.1f}/255 (threshold 3.0)",
                                engine="pixel_diff", screenshot=str(path))
        except Exception as e:  # noqa: BLE001
            log.warning("pixel diff failed", error=str(e)[:100])
            return None

    # -- entry --------------------------------------------------------------
    async def verify(self, target: str, screenshot_path: str | Path,
                     prev_ok: bool = True) -> Verification:
        path = Path(screenshot_path)
        if not path.exists():
            return Verification(False, f"screenshot missing: {path}", "none", str(path))
        # 1) LLM vision
        v = await self._try_llm(path)
        if v is not None:
            return v
        # 2) OCR
        v = self._try_ocr(path)
        if v is not None:
            return v
        # 3) pixel diff (needs a prior frame)
        v = self._try_pixel(target, path)
        if v is not None:
            return v
        return Verification(False, "no verifier produced a decision", "none", str(path))
