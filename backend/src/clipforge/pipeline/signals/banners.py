"""Big on-screen game banners (WASTED, VICTORY, MISSION PASSED...) via local OCR.

Reads the centre band of one frame per second from the proxy. Frames that look the
same as the last one read are skipped, so static scenes cost almost nothing.
Off by default (slow on CPU: roughly 5-15 min per hour of video).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from clipforge.pipeline.signals import Spike

DEFAULT_WORDS = [
    "WASTED",
    "BUSTED",
    "MISSION PASSED",
    "MISSION FAILED",
    "MISSION COMPLETE",
    "VICTORY",
    "DEFEAT",
    "GAME OVER",
    "YOU DIED",
    "ELIMINATED",
    "WINNER",
    "LEVEL UP",
    "KNOCKED OUT",
    "NEW RECORD",
    "CHAMPION",
    "WANTED",
]


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9 ]+", " ", text.upper()).strip()


def banner_spikes(
    proxy: Path,
    offset_s: float,
    words: list[str] | None = None,
    *,
    ocr: Any | None = None,
    progress: Callable[[float], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[Spike]:
    targets = [(_norm(w), w.upper()) for w in (words or DEFAULT_WORDS) if w.strip()]
    if ocr is None:
        from rapidocr_onnxruntime import RapidOCR

        ocr = RapidOCR()
    cap = cv2.VideoCapture(str(proxy))
    fps = cap.get(cv2.CAP_PROP_FPS) or 4
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, round(fps))
    hits: list[tuple[float, str]] = []
    last: np.ndarray | None = None
    i = 0
    try:
        while True:
            ok = cap.grab()
            if not ok:
                break
            if i % step == 0:
                if is_cancelled and is_cancelled():
                    raise InterruptedError
                _, frame = cap.retrieve()
                h, w = frame.shape[:2]
                band = frame[int(h * 0.25) : int(h * 0.75), int(w * 0.08) : int(w * 0.92)]
                tiny = cv2.resize(cv2.cvtColor(band, cv2.COLOR_BGR2GRAY), (64, 24)).astype(
                    np.float32
                )
                if last is None or float(np.mean(np.abs(tiny - last))) > 6.0:
                    last = tiny
                    big = cv2.resize(band, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                    result, _ = ocr(big)
                    text = _norm(" ".join(r[1] for r in (result or []) if float(r[2]) > 0.6))
                    for key, label in targets:
                        if key and key in text:
                            hits.append((offset_s + i / fps, label))
                if progress and total:
                    progress(min(99.0, i / total * 100))
            i += 1
    finally:
        cap.release()
    out: list[Spike] = []
    for t, label in sorted(hits):
        if out and out[-1].label == label and t - out[-1].end <= 3:
            out[-1].end = t + 1
        else:
            out.append(Spike("banner", t, t + 1, 1.0, label, {"word": label}))
    return out
