"""Callback finder: an earlier claim/bet/prediction that pays off later.

"I bet I can jump that" ... 40 minutes later ... a loud crash. Such pairs make
strong two-part Shorts (claim -> hard cut -> payoff). This only finds candidates;
the AI or a human decides which are real.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from clipforge.pipeline.selection import Sent
from clipforge.pipeline.selection.heuristic import STOP, WORD

CLAIM = re.compile(
    r"\b(i bet|watch (?:this|me)|i told you|trust me|i promise|i swear|easy|no way i|"
    r"i'?m (?:a|the) (?:pro|best|god)|i'?ll never|i will never|y'?all thought|"
    r"guarantee|there'?s no way|i can do (?:this|it)|calling it|mark my words)\b",
    re.I,
)


@dataclass(frozen=True)
class CallbackPair:
    setup: Sent
    payoff: Sent
    shared: tuple[str, ...]
    gap_s: float
    score: float


def _nouns(text: str) -> set[str]:
    return {w.lower() for w in WORD.findall(text) if w.lower() not in STOP and len(w) > 3}


def find_callbacks(
    sents: list[Sent],
    *,
    payoff_heat: float = 50.0,
    min_gap_s: float = 60.0,
    max_gap_s: float = 3 * 3600.0,
    limit: int = 10,
) -> list[CallbackPair]:
    out: list[CallbackPair] = []
    claims = [s for s in sents if CLAIM.search(s.text)]
    for p in sents:
        if p.heat < payoff_heat:
            continue
        pn = _nouns(p.text)
        for c in claims:
            gap = p.start - c.end
            if not (min_gap_s <= gap <= max_gap_s):
                continue
            shared = tuple(sorted(pn & _nouns(c.text)))
            if not shared:
                continue
            out.append(CallbackPair(c, p, shared, gap, round(p.heat * (1 + 0.2 * len(shared)), 1)))
    out.sort(key=lambda x: -x.score)
    return out[:limit]
