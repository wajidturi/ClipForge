"""Deep mode: whole action scenes found from the picture and the sound.

Speech-based windows miss what gameplay is about: a car chase, a shoot-out, an escape
from the police. Here a scene is a stretch where the picture moves much more than
usual for this video (and the sound is up), kept whole however long it runs, from a
few seconds of build-up to the moment things calm down again. Boundaries snap to the
nearest scene cut so a Short does not start or end mid-shot.

Pure functions (no database) so they are easy to test.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

MIN_SCENE_S = 12.0
MAX_SCENE_S = 600.0  # longer stretches are split at their calmest point
GAP_S = 5.0  # a lull shorter than this does not end a scene
LEAD_S = 3.0  # build-up kept before the action starts
TAIL_S = 2.0
SNAP_S = 3.0  # move a boundary to a scene cut this close
BASE_WIN_S = 181  # rolling baseline: "usual for this part of the video"
SPIKE_KINDS = ("action", "impact", "loud", "chat", "clip", "replay", "laugh", "reaction")


@dataclass
class Scene:
    start: float
    end: float
    score: float  # 0..100
    peak: float
    kinds: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Activity:
    """Per-second series on one time axis (index i covers [offset + i, offset + i + 1))."""

    offset: float
    motion: np.ndarray
    loud: np.ndarray

    @property
    def end(self) -> float:
        return self.offset + len(self.motion)


def _rolling(v: np.ndarray, win: int, fn: str) -> np.ndarray:
    """Rolling median/mean on a downsampled grid (fast on 5 h streams)."""
    if len(v) == 0:
        return v
    step = max(1, win // 30)
    pts = np.arange(0, len(v), step)
    half = win // 2
    f = np.median if fn == "median" else np.mean
    vals = np.array([f(v[max(0, i - half) : i + half + 1]) for i in pts], dtype=np.float32)
    return np.interp(np.arange(len(v)), pts, vals).astype(np.float32)


def activity_from_curves(curves: dict[str, object]) -> Activity | None:
    motion = curves.get("motion")
    if not isinstance(motion, list) or len(motion) < MIN_SCENE_S:
        return None
    offset = float(curves.get("motion_offset_s") or 0.0)  # type: ignore[arg-type]
    m = np.nan_to_num(np.asarray(motion, dtype=np.float32))
    loud = curves.get("loud")
    out = np.zeros_like(m)
    if isinstance(loud, list) and loud:
        hop = float(curves.get("hop_s") or 2.0)  # type: ignore[arg-type]
        l_off = float(curves.get("loud_offset_s") or 0.0)  # type: ignore[arg-type]
        lv = np.nan_to_num(np.asarray(loud, dtype=np.float32))
        t = offset + np.arange(len(m)) + 0.5
        idx = ((t - l_off) / hop).astype(int)
        ok = (idx >= 0) & (idx < len(lv))
        out[ok] = lv[idx[ok]]
    return Activity(offset, m, out)


def intensity(a: Activity) -> np.ndarray:
    """0..~2 per second: picture motion against this video's usual level, lifted by
    loud sound. Gameplay that is always moving still shows its peaks."""
    m = a.motion
    base = np.maximum(_rolling(m, BASE_WIN_S, "median"), 1e-3)
    hi = max(float(np.percentile(m, 97)), 1e-3)
    rel = np.clip(m / base, 0, 4) / 4  # against the local baseline
    absl = np.clip(m / hi, 0, 1.2)  # against the whole video
    x = 0.55 * rel + 0.45 * absl
    if a.loud.any():
        x = x * (0.75 + 0.5 * np.clip(a.loud, 0, 1))
    return _rolling(x.astype(np.float32), 5, "mean")


def _snap(t: float, cuts: list[float], lo: float, hi: float, before: bool) -> float:
    near = [c for c in cuts if abs(c - t) <= SNAP_S and lo <= c <= hi]
    if not near:
        return t
    side = [c for c in near if (c <= t if before else c >= t)] or near
    return min(side, key=lambda c: abs(c - t))


def _split(s: int, e: int, x: np.ndarray, max_len: int) -> list[tuple[int, int]]:
    if e - s <= max_len:
        return [(s, e)]
    q = (e - s) // 4
    cut = s + q + int(np.argmin(x[s + q : e - q]))
    return _split(s, cut, x, max_len) + _split(cut, e, x, max_len)


def find_scenes(
    a: Activity,
    *,
    cuts: list[float] | None = None,
    spikes: list[tuple[float, float, str]] | None = None,
    window: tuple[float, float | None] | None = None,
    exclude: list[tuple[float, float]] | None = None,
    min_len: float = MIN_SCENE_S,
    max_len: float = MAX_SCENE_S,
) -> list[Scene]:
    """Action scenes, best first. `spikes` are (start, end, kind) marks from analysis
    (impacts, loud bursts, chat spikes) that add to a scene's score."""
    x = intensity(a)
    if len(x) == 0:
        return []
    cuts = sorted(cuts or [])
    # "Busy" = well up from this video's calm level towards its peaks (a video that is
    # mostly action still splits into its scenes); the floor stops a very still video
    # from turning noise into scenes.
    lo, hi = float(np.percentile(x, 20)), float(np.percentile(x, 95))
    thr = max(lo + 0.45 * (hi - lo), 0.12)
    busy = x >= thr
    # close short lulls
    gap = int(GAP_S)
    runs: list[tuple[int, int]] = []
    i, n = 0, len(busy)
    while i < n:
        if not busy[i]:
            i += 1
            continue
        j = i
        while j < n and busy[j]:
            j += 1
        if runs and i - runs[-1][1] <= gap:
            runs[-1] = (runs[-1][0], j)
        else:
            runs.append((i, j))
        i = j
    lo_t = a.offset if window is None else max(a.offset, window[0])
    hi_t = a.end if window is None or window[1] is None else min(a.end, float(window[1]))
    out: list[Scene] = []
    for s0, e0 in runs:
        for s, e in _split(s0, e0, x, int(max_len)):
            start = max(lo_t, a.offset + s - LEAD_S)
            end = min(hi_t, a.offset + e + TAIL_S)
            start = _snap(start, cuts, lo_t, end, before=True)
            end = _snap(end, cuts, start, hi_t, before=False)
            if end - start < min_len:
                continue
            if exclude and any(min(end, b) - max(start, a_) > 0.5 * (end - start)
                               for a_, b in exclude):  # fmt: skip
                continue
            i0, i1 = int(start - a.offset), max(int(start - a.offset) + 1, int(end - a.offset))
            seg = x[i0:i1]
            kinds = sorted(
                {k for ks, ke, k in spikes or [] if ks < end and ke > start and k in SPIKE_KINDS}
            )
            marks = sum(1 for ks, ke, _ in spikes or [] if ks < end and ke > start)
            # Strong on average, with peaks; longer scenes earn a little (not linearly:
            # a 5-minute drive is not 10x better than a 30 s shoot-out).
            core = 0.6 * float(np.mean(seg)) + 0.4 * float(np.percentile(seg, 90))
            length = 1 + 0.18 * math.log2(1 + (end - start) / 20)
            bonus = 1 + min(0.3, 0.04 * marks) + 0.03 * len(kinds)
            score = 100 * math.tanh(core * length * bonus / 1.6)
            peak = a.offset + i0 + int(np.argmax(seg))
            out.append(Scene(round(start, 2), round(end, 2), round(score, 1), float(peak), kinds))
    out.sort(key=lambda sc: -sc.score)
    return out
