"""Candidate windows: whole-sentence ranges that could become a Short.

For every starting sentence we grow the window sentence by sentence (up to
`max_len`) and score each version. A good window has a hot peak, some build-up
before it (a premise), the payoff in its second half, enough speech, and does not
open mid-thought ("and...", "so...", "he..."). Overlapping windows are then thinned
greedily (best first), so the candidate list covers different moments.
"""

from __future__ import annotations

import re

from clipforge.pipeline.selection import Candidate, Sent

BAD_OPENERS = re.compile(
    r"^\s*(and|but|so|or|because|then|also|which|that|he|she|it|they|them|this|those|these|"
    r"yeah|yes|no|okay|ok|right|um|uh)\b",
    re.I,
)


def talk_time(sents: list[Sent]) -> float:
    return sum(s.duration for s in sents)


def _words(text: str, n: int, from_end: bool = False) -> str:
    w = text.split()
    if len(w) <= n:
        return text.strip()
    return ("… " + " ".join(w[-n:])) if from_end else (" ".join(w[:n]) + " …")


def window_score(sents: list[Sent], *, min_talk: float) -> float:
    """0..100. Peak heat dominates; build-up, payoff position and speech amount adjust."""
    heats = [s.heat for s in sents]
    peak = max(heats)
    if peak <= 0:
        return 0.0
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
    if talk_time(sents) < min_talk:
        score -= 20
    # the payoff should not be the very last half second of speech
    if i_peak == len(sents) - 1 and len(sents) > 1:
        score -= 2
    return max(0.0, min(100.0, score))


def build_candidates(
    sents: list[Sent],
    *,
    min_len: float = 15.0,
    max_len: float = 60.0,
    min_talk: float = 12.0,
    k: int = 30,
    exclude: list[tuple[float, float]] | None = None,
    start_id: int = 1,
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
            s = window_score(win, min_talk=min_talk)
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
