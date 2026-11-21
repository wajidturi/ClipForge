"""Signals: time ranges in a source that hint at a good moment (loud, chat spike,
viewer clip, most replayed, visual action, on-screen banner...). All times are
full-video seconds. Each extractor is pure: inputs in, `Spike` list out."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Spike:
    type: str  # matches db.enums.SignalType values
    start: float
    end: float
    score: float  # 0..1 strength
    label: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def binned_max(values: Any, bins: int) -> list[float]:
    """Downsample a 1-D series to `bins` points, keeping each bin's peak (for graphs)."""
    from itertools import pairwise

    import numpy as np

    v = np.asarray(values, dtype=np.float32)
    if len(v) == 0 or bins <= 0:
        return []
    edges = np.linspace(0, len(v), bins + 1).astype(int)
    return [float(v[a:b].max()) if b > a else 0.0 for a, b in pairwise(edges)]


def merge_runs(
    flags: list[bool], hop: float, offset: float = 0.0, min_len: float = 0.0
) -> list[tuple[float, float]]:
    """Consecutive True bins -> (start, end) ranges in seconds."""
    out: list[tuple[float, float]] = []
    start: int | None = None
    for i, f in enumerate([*flags, False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            s, e = offset + start * hop, offset + i * hop
            if e - s >= min_len:
                out.append((s, e))
            start = None
    return out
