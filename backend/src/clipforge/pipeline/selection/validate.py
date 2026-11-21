"""Make any pick (AI or not) safe to render.

- snap start/end to whole sentences (never cut a word or a thought in half)
- enough speech (talk time) and not too long
- no overlap with other picks or with ranges already used by earlier Shorts
- at most `per_source` picks from one source
- texts trimmed to their limits (hook <= 6 words, title <= 70 chars, 3-5 hashtags)
"""

from __future__ import annotations

import bisect
import re

from clipforge.pipeline.selection import Pick, Sent
from clipforge.pipeline.selection.windows import BAD_OPENERS, talk_time

MIN_TALK_S = 12.0
MAX_SPAN_S = 90.0
HOOK_WORDS = 6
TITLE_CHARS = 70


def snap(sents: list[Sent], start: float, end: float) -> tuple[int, int] | None:
    """Indices of the first/last sentence of [start, end], expanded to whole sentences."""
    if not sents or end <= start:
        return None
    starts = [s.start for s in sents]
    i = max(0, bisect.bisect_right(starts, start + 0.25) - 1)
    if sents[i].end <= start:  # start fell in a gap: take the next sentence
        i = min(i + 1, len(sents) - 1)
    j = max(i, bisect.bisect_left(starts, end - 0.25) - 1)
    j = min(j, len(sents) - 1)
    return i, j


def clean_hook(text: str) -> str:
    words = re.sub(r"\s+", " ", text or "").strip().strip("\"'").split(" ")
    return " ".join(words[:HOOK_WORDS]).upper().rstrip(".,;:")


def clean_title(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip().strip("\"'")
    return t if len(t) <= TITLE_CHARS else t[: TITLE_CHARS - 1].rstrip() + "…"


def clean_hashtags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        tag = "#" + re.sub(r"[^\w]", "", t.lstrip("#")).lower()
        if len(tag) > 1 and tag not in out:
            out.append(tag)
    if "#shorts" not in out:
        out.append("#shorts")
    return out[:5]


def validate(
    picks: list[Pick],
    sents_by_source: dict[str, list[Sent]],
    *,
    n: int,
    per_source: int = 2,
    used: dict[str, list[tuple[float, float]]] | None = None,
    min_talk: float = MIN_TALK_S,
    max_span: float = MAX_SPAN_S,
) -> tuple[list[Pick], list[Pick]]:
    """Returns (accepted, rejected). Rejected picks carry the reasons in `issues`."""
    used = used or {}
    accepted: list[Pick] = []
    rejected: list[Pick] = []
    count: dict[str, int] = {}
    for p in picks:
        sents = sents_by_source.get(p.source_id) or []
        ij = snap(sents, p.start, p.end)
        if ij is None:
            p.issues.append("range is outside the transcript")
            rejected.append(p)
            continue
        i, j = ij
        win = sents[i : j + 1]
        p.start, p.end = win[0].start, win[-1].end
        if talk_time(win) < min_talk:
            p.issues.append(f"TOO SHORT: {talk_time(win):.0f}s of speech (needs {min_talk:.0f}s)")
        if p.duration > max_span:
            p.issues.append(f"TOO LONG: {p.duration:.0f}s (max {max_span:.0f}s)")
        taken = used.get(p.source_id, []) + [
            (a.start, a.end) for a in accepted if a.source_id == p.source_id
        ]
        if any(p.start < b and p.end > a for a, b in taken):
            p.issues.append("overlaps a moment that is already used")
        if count.get(p.source_id, 0) >= per_source:
            p.issues.append(f"already {per_source} Shorts from this source")
        if len(accepted) >= n:
            p.issues.append("enough Shorts already")
        if p.issues:
            rejected.append(p)
            continue
        if BAD_OPENERS.match(win[0].text):
            p.meta["warning"] = "opens mid-thought; consider starting a sentence earlier"
        p.hook = clean_hook(p.hook) or clean_hook(win[-1].text)
        p.title = clean_title(p.title) or clean_title(win[0].text)
        p.hashtags = clean_hashtags(p.hashtags)
        p.keywords = [k.strip().upper() for k in p.keywords if k.strip()][:3]
        count[p.source_id] = count.get(p.source_id, 0) + 1
        accepted.append(p)
    return accepted, rejected
