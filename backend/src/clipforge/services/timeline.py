"""Read models for a source's analysis: the timeline graph data."""

from __future__ import annotations

import uuid
from itertools import pairwise
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipforge.core.config import Settings
from clipforge.db.models import Segment, Signal, Source, Transcript
from clipforge.services.analyze import load_curves

MARKER_TYPES = ("loud", "chat_spike", "clip", "replay", "moment", "banner", "laugh")


def _resample(
    values: list[float], hop: float, offset: float, start: float, end: float, bins: int
) -> list[float]:
    """Series sampled every `hop` s from `offset` -> `bins` values across [start, end].

    Bins holding samples keep their peak (short spikes stay visible when zoomed out).
    Bins finer than the sampling (short sources) interpolate between neighbours instead
    of dropping to zero, which would draw a comb of fake spikes.
    """
    if not values or end <= start:
        return [0.0] * bins
    v = np.asarray(values, dtype=np.float32)
    t = offset + (np.arange(len(v)) + 0.5) * hop  # each sample describes its hop's centre
    edges = np.linspace(start, end, bins + 1)
    out = []
    for a, b in pairwise(edges):
        sel = v[(t >= a) & (t < b)]
        if len(sel):
            out.append(float(sel.max()))
        else:
            out.append(float(np.interp((a + b) / 2, t, v, left=0.0, right=0.0)))
    return out


def _norm(v: list[float]) -> list[float]:
    m = max(v) if v else 0.0
    return [x / m for x in v] if m > 0 else v


def build_timeline(db: Session, settings: Settings, src: Source, bins: int) -> dict[str, Any]:
    start = src.window_start_s or 0.0
    end = src.window_end_s or src.duration_s or 0.0
    curves = load_curves(settings, src.id)
    segs = db.execute(
        select(Segment.start_s, Segment.end_s, Segment.heat)
        .join(Transcript, Transcript.id == Segment.transcript_id)
        .where(Transcript.source_id == src.id)
        .order_by(Segment.start_s)
    ).all()
    if not end and segs:
        end = float(segs[-1].end_s)
    heat = [0.0] * bins
    if end > start:
        width = (end - start) / bins
        for s, e, h in segs:
            for i in range(int((s - start) // width), int((e - start) // width) + 1):
                if 0 <= i < bins:
                    heat[i] = max(heat[i], float(h))

    hop = float(curves.get("hop_s", 2.0))
    loud = _resample(
        curves.get("loud", []), hop, curves.get("loud_offset_s", start), start, end, bins
    )
    chat = _norm(
        _resample(
            curves.get("chat", []),
            float(curves.get("chat_bin_s", 10.0)),
            curves.get("chat_offset_s", start),
            start,
            end,
            bins,
        )
    )
    motion = curves.get("motion", [])
    motion_b = _norm(_resample(motion, 1.0, curves.get("motion_offset_s", start), start, end, bins))
    replay_pts = curves.get("replay", [])
    replay = [0.0] * bins
    if replay_pts and end > start:
        width = (end - start) / bins
        top = max(p["value"] for p in replay_pts) or 1.0
        for p in replay_pts:
            for i in range(
                int((p["start"] - start) // width), int((p["end"] - start) // width) + 1
            ):
                if 0 <= i < bins:
                    replay[i] = max(replay[i], p["value"] / top)

    sigs = db.scalars(
        select(Signal)
        .where(Signal.source_id == src.id, Signal.type.in_(MARKER_TYPES))
        .order_by(Signal.score.desc())
        .limit(400)
    ).all()
    analysis = (src.meta or {}).get("analysis") or {}
    return {
        "start_s": start,
        "end_s": end,
        "bins": bins,
        "heat": heat,
        "loud": loud,
        "chat": chat,
        "motion": motion_b,
        "replay": replay,
        "markers": [
            {
                "type": s.type.value,
                "start_s": s.start_s,
                "end_s": s.end_s,
                "score": s.score,
                "label": s.label,
            }
            for s in sorted(sigs, key=lambda x: x.start_s)
        ],
        "available": analysis.get("available", []),
        "steps": analysis.get("steps", {}),
        "warnings": analysis.get("warnings", []),
    }


def transcript_for(db: Session, source_id: uuid.UUID) -> tuple[Transcript | None, list[Segment]]:
    tr = db.scalar(select(Transcript).where(Transcript.source_id == source_id))
    if tr is None:
        return None, []
    segs = list(
        db.scalars(select(Segment).where(Segment.transcript_id == tr.id).order_by(Segment.idx))
    )
    return tr, segs
