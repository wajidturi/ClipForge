"""No-AI picker ("Free" mode): best candidates by score, plus rule-based text.

Free, offline and deterministic. It cannot judge meaning (premise, payoff, spoilers),
so its picks are weaker than an AI's; the review step is where a human catches that.
"""

from __future__ import annotations

import re
from collections import Counter

from clipforge.pipeline.selection import Candidate, Pick

_STOP_WORDS = """
a an the and or but so to of in on at for with from by is are was were be been am i you he she
it we they me him her them my your his its our their this that these those there here what
which who whom how why when where not no yes yeah oh okay ok like just really very do does did
done have has had get got go going gonna wanna can could would should will shall may might
must one all any some more most then than now out up down over about into um uh hmm
let's lets im i'm you're it's that's don't doesn't didn't can't won't isn't aren't
"""
STOP = frozenset(_STOP_WORDS.split())
WORD = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")


def keywords(text: str, k: int = 3) -> list[str]:
    c = Counter(w.lower() for w in WORD.findall(text) if w.lower() not in STOP)
    return [w.upper() for w, _ in c.most_common(k)]


def _jaccard(a: str, b: str) -> float:
    sa, sb = set(WORD.findall(a.lower())), set(WORD.findall(b.lower()))
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def heuristic_picks(
    candidates: list[Candidate],
    *,
    n: int,
    credit_for: dict[str, str | None],
    per_source: int = 2,
) -> list[Pick]:
    picks: list[Pick] = []
    per: Counter[str] = Counter()
    for c in sorted(candidates, key=lambda x: -x.score):
        if len(picks) >= n:
            break
        if per[c.source_id] >= per_source:
            continue
        if any(_jaccard(c.text, p.meta["text"]) > 0.5 for p in picks):
            continue  # same point twice
        kw = keywords(c.text)
        credit = credit_for.get(c.source_id)
        hook_core = " ".join(kw[:2]) if kw else "WAIT FOR IT"
        hook = f"{credit.split()[0]} {hook_core}" if credit else hook_core
        first_sentence = re.split(r"(?<=[.!?])\s", c.text.strip(), maxsplit=1)[0]
        title = f"{credit}: {first_sentence}" if credit else first_sentence
        picks.append(
            Pick(
                source_id=c.source_id,
                start=c.start,
                end=c.end,
                hook=hook,
                title=title,
                hashtags=[k.lower() for k in kw[:3]],
                keywords=kw,
                credit=credit,
                score=c.score,
                reason="highest signal score: " + (", ".join(c.tags) or "speech"),
                candidate_id=c.id,
                meta={"text": c.text},
            )
        )
        per[c.source_id] += 1
    return picks
