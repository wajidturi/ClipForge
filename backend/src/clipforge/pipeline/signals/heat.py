"""HEAT: every sentence gets 0-100 from the signals around it, plus readable tags.

Weights are re-normalised over the signal types that exist for this source, so an
uploaded file (no chat, no viewer clips) can still reach high scores. Two or more
independent strong signals at the same moment get a bonus: agreement is the best
predictor of a moment worth clipping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clipforge.pipeline.signals import Spike

WEIGHTS: dict[str, float] = {
    "loud": 0.25,
    "chat_spike": 0.25,
    "clip": 0.15,
    "replay": 0.15,
    "moment": 0.10,
    "banner": 0.05,
    "laugh": 0.05,
}
TAG_NAMES = {
    "loud": "LOUD",
    "chat_spike": "CHAT",
    "clip": "CLIPPED",
    "replay": "REPLAYED",
    "moment": "MOMENT",
    "banner": "GAME",
    "laugh": "LAUGH",
}
AGREEMENT_BONUS = 1.25
PAD_S = 2.0


@dataclass
class Scored:
    heat: float
    tags: list[dict[str, Any]]


def score_ranges(
    ranges: list[tuple[float, float]],
    spikes: list[Spike],
    available: set[str],
    *,
    pad_s: float = PAD_S,
) -> list[Scored]:
    usable = sorted((s for s in spikes if s.type in WEIGHTS), key=lambda s: s.start)
    denom = sum(WEIGHTS[t] for t in available if t in WEIGHTS) or 1.0
    out: list[Scored] = []
    j0 = 0
    for start, end in ranges:
        lo, hi = start - pad_s, end + pad_s
        while j0 < len(usable) and usable[j0].end < lo - 600:  # cheap forward scan
            j0 += 1
        best: dict[str, Spike] = {}
        for sp in usable[j0:]:
            if sp.start > hi:
                break
            if sp.end >= lo and (sp.type not in best or sp.score > best[sp.type].score):
                best[sp.type] = sp
        raw = sum(WEIGHTS[t] * sp.score for t, sp in best.items()) / denom
        if sum(sp.score >= 0.3 for sp in best.values()) >= 2:
            raw *= AGREEMENT_BONUS
        tags = [
            {"type": TAG_NAMES[t], "label": sp.label, "score": round(sp.score, 2)}
            for t, sp in sorted(best.items(), key=lambda kv: -WEIGHTS[kv[0]] * kv[1].score)
        ]
        out.append(Scored(round(min(100.0, raw * 100), 1), tags))
    return out
