"""YouTube "most replayed" heat map (from yt-dlp metadata) -> replay signals."""

from __future__ import annotations

from typing import Any

from clipforge.pipeline.signals import Spike


def replay_spikes(
    heatmap: list[dict[str, Any]], start: float, end: float, *, threshold: float = 0.6
) -> list[Spike]:
    pts = [h for h in heatmap if h.get("value") is not None and h.get("start") is not None]
    if not pts:
        return []
    top = max(float(h["value"]) for h in pts) or 1.0
    out: list[Spike] = []
    run: list[dict[str, Any]] = []

    def flush() -> None:
        if run:
            peak = max(float(h["value"]) for h in run) / top
            s, e = float(run[0]["start"]), float(run[-1]["end"] or run[-1]["start"])
            if e >= start and s <= end:
                out.append(
                    Spike(
                        "replay", s, e, peak, f"most replayed {peak:.0%}", {"peak": round(peak, 2)}
                    )
                )
            run.clear()

    for h in sorted(pts, key=lambda x: float(x["start"])):
        if float(h["value"]) / top >= threshold:
            run.append(h)
        else:
            flush()
    flush()
    return out


def replay_curve(heatmap: list[dict[str, Any]]) -> list[dict[str, float]]:
    return [
        {"start": float(h["start"]), "end": float(h["end"]), "value": float(h["value"])}
        for h in heatmap
        if h.get("value") is not None and h.get("start") is not None and h.get("end") is not None
    ]
