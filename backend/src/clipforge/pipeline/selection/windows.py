"""Candidate windows: whole-sentence ranges that could become a Short.

For every starting sentence we grow the window sentence by sentence (up to
`max_len`) and score each version. A good window has a hot peak, some build-up
before it (a premise), the payoff in its second half, enough speech, and does not
open mid-thought ("and...", "so...", "he..."). Overlapping windows are then thinned
greedily (best first), so the candidate list covers different moments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from clipforge.pipeline.selection import Candidate, Sent

BAD_OPENERS = re.compile(
    r"^\s*(and|but|so|or|because|then|also|which|that|he|she|it|they|them|this|those|these|"
    r"yeah|yes|no|okay|ok|right|um|uh)\b",
    re.I,
)


LengthPreset = Literal["short", "medium", "long"]


@dataclass(frozen=True)
class Lengths:
    """How long candidate windows are, how much speech they need, and the hard cap
    after snapping to whole sentences / AI nudges (YouTube Shorts allow 3 minutes)."""

    min_len: float
    max_len: float
    min_talk: float
    max_span: float
    target: float | None = None  # preferred length; None = shortest good window wins


LENGTHS: dict[str, Lengths] = {
    "short": Lengths(15, 60, 12, 90),  # classic Shorts
    "medium": Lengths(30, 90, 20, 120, target=60),
    "long": Lengths(45, 170, 30, 180, target=100),  # a whole scene, up to 3 minutes
}


def talk_time(sents: list[Sent]) -> float:
    return sum(s.duration for s in sents)


def _words(text: str, n: int, from_end: bool = False) -> str:
    w = text.split()
    if len(w) <= n:
        return text.strip()
    return ("… " + " ".join(w[-n:])) if from_end else (" ".join(w[:n]) + " …")


def window_score(
    sents: list[Sent], *, min_talk: float, target: float | None = None, quiet_ok: bool = False
) -> float:
    """0..100. Peak heat dominates; build-up, payoff position and speech amount adjust.
    With a `target` length, windows near it are preferred (otherwise the mean heat makes
    the shortest window around a peak win, which is right for classic Shorts only)."""
    heats = [s.heat for s in sents]
    peak = max(heats)
    if peak <= 0:
        return _quiet_score(sents, min_talk=min_talk, target=target) if quiet_ok else 0.0
    mean = sum(heats) / len(heats)
    score = 0.65 * peak + 0.35 * mean
    i_peak = heats.index(peak)
    span = sents[-1].end - sents[0].start
    pos = (sents[i_peak].start - sents[0].start) / span if span > 0 else 0.0
    if pos >= 0.4:  # payoff in the back half: the viewer sees it land
        score += 6
    elif pos < 0.15:  # opens on the peak with no premise
        score -= 8
    kinds = {t for s in sents for t in s.tags}
    score += 3 * max(0, len(kinds) - 1)  # independent signals agree
    if BAD_OPENERS.match(sents[0].text):
        score -= 10
    if target:
        score -= 8 * abs(span - target) / target
    if talk_time(sents) < min_talk:
        score -= 20
    # the payoff should not be the very last half second of speech
    if i_peak == len(sents) - 1 and len(sents) > 1:
        score -= 2
    score = max(0.0, min(100.0, score))
    if quiet_ok and score <= 0:
        return _quiet_score(sents, min_talk=min_talk, target=target)
    return score


def _quiet_score(sents: list[Sent], *, min_talk: float, target: float | None) -> float:
    """A part the user chose themselves may be calm: rank its windows by speech alone,
    always above zero (so they count) and below windows with a real peak."""
    span = sents[-1].end - sents[0].start
    talk = talk_time(sents)
    score = 8.0 + min(8.0, talk / 5)
    if BAD_OPENERS.match(sents[0].text):
        score -= 3
    if target:
        score -= 4 * abs(span - target) / target
    if talk < min_talk:
        score -= 5
    return max(0.5, score)


def build_candidates(
    sents: list[Sent],
    *,
    min_len: float = 15.0,
    max_len: float = 60.0,
    min_talk: float = 12.0,
    target: float | None = None,
    k: int = 30,
    exclude: list[tuple[float, float]] | None = None,
    start_id: int = 1,
    quiet_ok: bool = False,
) -> list[Candidate]:
    """`sents` must belong to one source, sorted by time."""
    exclude = exclude or []
    scored: list[tuple[float, int, int]] = []
    for i in range(len(sents)):
        for j in range(i, len(sents)):
            span = sents[j].end - sents[i].start
            if span > max_len:
                break
            if span < min_len:
                continue
            win = sents[i : j + 1]
            s = window_score(win, min_talk=min_talk, target=target, quiet_ok=quiet_ok)
            if s > 0:
                scored.append((s, i, j))
    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen: list[tuple[float, int, int]] = []
    for s, i, j in scored:
        a, b = sents[i].start, sents[j].end
        if any(a < y and b > x for x, y in exclude):
            continue
        if any(a < sents[cj].end and b > sents[ci].start for _, ci, cj in chosen):
            continue
        chosen.append((s, i, j))
        if len(chosen) >= k:
            break
    out: list[Candidate] = []
    for n, (s, i, j) in enumerate(chosen):
        win = sents[i : j + 1]
        peak_s = max(win, key=lambda x: x.heat)
        text = " ".join(x.text for x in win)
        out.append(
            Candidate(
                id=start_id + n,
                source_id=win[0].source_id,
                start=win[0].start,
                end=win[-1].end,
                score=round(s, 1),
                first=win[0].idx,
                last=win[-1].idx,
                peak=peak_s.start,
                tags=sorted({t for x in win for t in x.tags}),
                head=_words(text, 25),
                tail=_words(text, 25, from_end=True),
                text=text,
            )
        )
    return out
