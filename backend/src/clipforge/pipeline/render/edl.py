"""Edit decision list: which parts of the source to keep.

Shorts feel fast because pauses are gone. From word timings we keep speech and
shrink every silence longer than `max_gap` to `keep_gap`, and drop standalone
fillers ("um", "uh"). Times here are full-video seconds; `map()` converts a source
time into output time (or None when that moment was cut).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from clipforge.pipeline.transcription.sentences import Word

FILLER = re.compile(r"^\W*(um+|uh+|erm+|hmm+|uhm+|ah+|eh+)\W*$", re.I)


@dataclass(frozen=True)
class Span:
    start: float  # full-video seconds
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class Edl:
    spans: tuple[Span, ...]

    @property
    def duration(self) -> float:
        return sum(s.duration for s in self.spans)

    @property
    def start(self) -> float:
        return self.spans[0].start

    @property
    def end(self) -> float:
        return self.spans[-1].end

    def map(self, t: float) -> float | None:
        """Source time -> output time; None if `t` falls in a cut."""
        acc = 0.0
        for s in self.spans:
            if s.start <= t <= s.end:
                return acc + (t - s.start)
            acc += s.duration
        return None

    def map_clamped(self, t: float) -> float:
        """Like map(), but a time inside a cut snaps to the next kept moment."""
        acc = 0.0
        for s in self.spans:
            if t <= s.end:
                return acc + max(0.0, t - s.start)
            acc += s.duration
        return acc

    def to_json(self) -> list[list[float]]:
        return [[round(s.start, 3), round(s.end, 3)] for s in self.spans]


@dataclass(frozen=True)
class CaptionWord:
    start: float  # output seconds
    end: float
    text: str


def build_edl(
    words: list[Word],
    start: float,
    end: float,
    *,
    # Natural pauses between words are 0.2-0.5 s; cutting those sounds choppy.
    # Only dead air above `max_gap` is shortened to `keep_gap`.
    max_gap: float = 0.55,
    keep_gap: float = 0.2,
    lead: float = 0.15,
    tail: float = 0.45,
    drop_fillers: bool = True,
) -> Edl:
    inside = [w for w in words if w.start >= start - 0.05 and w.end <= end + 0.05]
    kept = [w for w in inside if not (drop_fillers and FILLER.match(w.text.strip()))]
    if not kept:
        return Edl((Span(start, end),))
    spans: list[Span] = []
    s0 = max(start - lead, kept[0].start - lead)
    prev = kept[0]
    for w in kept[1:]:
        gap = w.start - prev.end
        if gap > max_gap:
            spans.append(Span(s0, prev.end + keep_gap / 2))
            s0 = w.start - keep_gap / 2
        prev = w
    spans.append(Span(s0, min(end + tail, prev.end + tail)))
    # merge slivers (< 0.25 s) into their neighbour so the cut does not stutter
    merged: list[Span] = []
    for sp in spans:
        if merged and (sp.duration < 0.25 or sp.start - merged[-1].end < 0.02):
            merged[-1] = Span(merged[-1].start, sp.end)
        else:
            merged.append(sp)
    return Edl(tuple(merged))


def caption_words(words: list[Word], edl: Edl, *, drop_fillers: bool = True) -> list[CaptionWord]:
    """Words that survive the cut, in output time."""
    out: list[CaptionWord] = []
    for w in words:
        if drop_fillers and FILLER.match(w.text.strip()):
            continue
        a, b = edl.map(w.start), edl.map(w.end)
        if a is None or b is None:
            continue
        text = w.text.strip()
        if text:
            out.append(CaptionWord(a, max(b, a + 0.08), text))
    return out
