"""Measure pick quality against human-labelled moments (the eval harness).

A label set is a JSON list of {"source": "<external id or source id>", "start", "end"}.
A pick "hits" a label when they overlap by IoU >= `min_iou`. We report precision@N
(how many picks were good) and recall (how many good moments were found). Use it
to compare pick modes, prompts and models before changing defaults.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Range:
    source: str
    start: float
    end: float


def iou(a: Range, b: Range) -> float:
    if a.source != b.source:
        return 0.0
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    union = max(a.end, b.end) - min(a.start, b.start)
    return inter / union if union > 0 else 0.0


@dataclass
class EvalResult:
    precision: float
    recall: float
    hits: int
    picks: int
    labels: int


def evaluate(picks: list[Range], labels: list[Range], *, min_iou: float = 0.3) -> EvalResult:
    matched: set[int] = set()
    hits = 0
    for p in picks:
        best = max(range(len(labels)), key=lambda i: iou(p, labels[i]), default=None)
        if best is not None and best not in matched and iou(p, labels[best]) >= min_iou:
            matched.add(best)
            hits += 1
    return EvalResult(
        precision=hits / len(picks) if picks else 0.0,
        recall=len(matched) / len(labels) if labels else 0.0,
        hits=hits,
        picks=len(picks),
        labels=len(labels),
    )
