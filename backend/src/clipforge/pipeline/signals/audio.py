"""Loudness: where the audio gets much louder than its recent baseline.

Streamers shout, laugh, scream at the moments viewers clip. A spike is measured
against a rolling median (so a loud stream is not 'always loud'), and must last.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from clipforge.core.ffmpeg import FFmpegError, _exe
from clipforge.pipeline.signals import Spike, binned_max, merge_runs

SR = 16000


def decode_pcm(path: Path, sr: int = SR) -> np.ndarray:
    """Mono float32 samples via ffmpeg (any input format)."""
    out = subprocess.run(
        [
            _exe("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(sr),
            "-f",
            "f32le",
            "-",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    if out.returncode != 0:
        raise FFmpegError(out.stderr.decode(errors="replace")[-300:])
    return np.frombuffer(out.stdout, dtype=np.float32)


def loudness_db(x: np.ndarray, sr: int = SR, hop_s: float = 0.5) -> np.ndarray:
    """RMS level in dBFS per hop."""
    hop = int(sr * hop_s)
    n = len(x) // hop
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    frames = x[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    return (20 * np.log10(np.maximum(rms, 1e-6))).astype(np.float32)


def rolling_median(v: np.ndarray, win: int) -> np.ndarray:
    """Centered rolling median (edges use a shrinking window)."""
    if len(v) == 0:
        return v
    half = max(1, win // 2)
    out = np.empty_like(v)
    for i in range(len(v)):
        out[i] = np.median(v[max(0, i - half) : i + half + 1])
    return out


def loud_spikes(
    db: np.ndarray,
    *,
    hop_s: float = 0.5,
    offset_s: float = 0.0,
    baseline_s: float = 60.0,
    min_rise_db: float = 8.0,
    min_len_s: float = 1.0,
    floor_db: float = -45.0,
) -> list[Spike]:
    if len(db) == 0:
        return []
    # Median over a coarse grid keeps this fast on 2-hour audio (14k bins).
    step = max(1, int(5 / hop_s))
    coarse = rolling_median(db[::step], max(3, int(baseline_s / hop_s / step)))
    base = np.interp(np.arange(len(db)), np.arange(len(coarse)) * step, coarse)
    rise = db - base
    flags = list((rise >= min_rise_db) & (db > floor_db))
    out: list[Spike] = []
    for s, e in merge_runs(flags, hop_s, offset_s, min_len_s):
        i0, i1 = int((s - offset_s) / hop_s), int((e - offset_s) / hop_s)
        peak = float(np.max(rise[i0:i1]))
        out.append(
            Spike(
                "loud", s, e, min(1.0, peak / 18.0), f"+{peak:.0f} dB", {"rise_db": round(peak, 1)}
            )
        )
    return out


def curve(db: np.ndarray, hop_s: float, offset_s: float, bins: int) -> list[float]:
    """Downsample the level curve for the timeline view (0..1)."""
    if len(db) == 0:
        return []
    lo, hi = np.percentile(db, 5), np.percentile(db, 99.5)
    return binned_max(np.clip((db - lo) / max(hi - lo, 1e-6), 0, 1), bins)
