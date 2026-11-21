"""Automatic quality check of a finished Short: PASS / WARN / FAIL with reasons.

One ffmpeg scan measures loudness (EBU R128), black stretches and frozen picture;
the first frame is checked for black/blank; caption coverage comes from the render.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from clipforge.core import ffmpeg

TARGET_LUFS = -14.0


@dataclass
class QcResult:
    verdict: str  # pass | warn | fail
    checks: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


def scan(video: Path) -> dict[str, Any]:
    out = subprocess.run(
        [
            ffmpeg._exe("ffmpeg"),
            "-hide_banner",
            "-nostdin",
            "-i",
            str(video),
            "-vf",
            "blackdetect=d=0.3:pix_th=0.08,freezedetect=n=0.003:d=1.0",
            "-af",
            "ebur128=framelog=quiet",
            "-f",
            "null",
            "-",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        timeout=600,
    )
    err = out.stderr
    lufs = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", err)
    blacks = [
        (float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)
    ]
    freezes = [float(d) for d in re.findall(r"freeze_duration: ([\d.]+)", err)]
    return {
        "lufs": float(lufs[-1]) if lufs and lufs[-1] != "-inf" else None,
        "black": blacks,
        "freeze_max_s": max(freezes, default=0.0),
    }


def first_frame_stats(video: Path) -> tuple[float, float]:
    cap = cv2.VideoCapture(str(video))
    ok, f = cap.read()
    cap.release()
    if not ok:
        return 0.0, 0.0
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(g.mean()), float(g.std())


def check(video: Path, *, caption_coverage: float, expected_s: float) -> QcResult:
    info = ffmpeg.probe(video)
    s = scan(video)
    mean, std = first_frame_stats(video)
    dur = info.duration_s or 0.0
    r = QcResult(
        "pass",
        {
            "duration_s": round(dur, 2),
            "expected_s": round(expected_s, 2),
            "lufs": s["lufs"],
            "black": s["black"],
            "freeze_max_s": round(s["freeze_max_s"], 2),
            "first_frame_mean": round(mean, 1),
            "first_frame_std": round(std, 1),
            "caption_coverage": round(caption_coverage, 3),
            "width": info.video.width if info.video else None,
            "height": info.video.height if info.video else None,
        },
    )

    def fail(msg: str) -> None:
        r.verdict = "fail"
        r.reasons.append(msg)

    def warn(msg: str) -> None:
        if r.verdict == "pass":
            r.verdict = "warn"
        r.reasons.append(msg)

    if not info.has_audio:
        fail("no audio track")
    if dur < 8:
        fail(f"too short ({dur:.1f}s)")
    elif dur > 120:
        fail(f"too long ({dur:.0f}s)")
    if abs(dur - expected_s) > 1.5:
        warn(f"length {dur:.1f}s differs from the plan ({expected_s:.1f}s)")
    if s["lufs"] is None:
        fail("silent audio")
    elif abs(s["lufs"] - TARGET_LUFS) > 3:
        fail(f"loudness {s['lufs']:.1f} LUFS (target {TARGET_LUFS:.0f})")
    elif abs(s["lufs"] - TARGET_LUFS) > 1.5:
        warn(f"loudness {s['lufs']:.1f} LUFS (target {TARGET_LUFS:.0f})")
    if any(a < 0.5 for a, _ in s["black"]) or mean < 12:
        fail("starts on a black frame")
    black_total = sum(b - a for a, b in s["black"])
    if black_total > 1.5:
        fail(f"{black_total:.1f}s of black picture")
    elif black_total > 0.4:
        warn(f"{black_total:.1f}s of black picture")
    if std < 6 and mean >= 12:
        warn("first frame is almost blank (menu, card or flat colour?)")
    if s["freeze_max_s"] > 3:
        fail(f"picture frozen for {s['freeze_max_s']:.1f}s")
    elif s["freeze_max_s"] > 1.5:
        warn(f"picture frozen for {s['freeze_max_s']:.1f}s")
    if caption_coverage < 0.9:
        warn(f"only {caption_coverage:.0%} of the speech is captioned")
    return r
