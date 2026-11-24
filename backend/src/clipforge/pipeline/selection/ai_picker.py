"""AI picker: ask a model to choose and write up the best candidates.

The model only chooses among our candidates (by id) and may nudge the range by
<= 10 s; anything else it says is clamped or dropped. Validation (validate.py)
then applies the same rules as for the no-AI picker.
"""

from __future__ import annotations

from clipforge.ai.base import Provider, Usage
from clipforge.ai.prompts import SELECT_SYSTEM, AIPickList, select_user_message
from clipforge.pipeline.selection import Candidate, Pick

MAX_NUDGE_S = 10.0


def ai_picks(
    provider: Provider,
    candidates: list[Candidate],
    *,
    n: int,
    credits: dict[str, str | None],
    topic: str | None = None,
    deep: bool = False,
    timeout: float = 300.0,
    length: tuple[float, float] = (15, 60),
) -> tuple[list[Pick], Usage, list[str]]:
    by_id = {c.id: c for c in candidates}
    user = select_user_message(
        candidates, n=n, credits=credits, topic=topic, deep=deep, length=length
    )
    answer, usage = provider.complete_json(SELECT_SYSTEM, user, AIPickList, timeout=timeout)
    notes: list[str] = []
    picks: list[Pick] = []
    seen: set[int] = set()
    for a in answer.picks:
        c = by_id.get(a.candidate_id)
        if c is None:
            notes.append(f"AI chose unknown candidate {a.candidate_id}; ignored")
            continue
        if a.candidate_id in seen:
            continue
        seen.add(a.candidate_id)
        start = (
            c.start
            if a.start is None
            else min(max(a.start, c.start - MAX_NUDGE_S), c.start + MAX_NUDGE_S)
        )
        end = c.end if a.end is None else min(max(a.end, c.end - MAX_NUDGE_S), c.end + MAX_NUDGE_S)
        if end <= start:
            start, end = c.start, c.end
        # Small local models often return 0; fall back to the signal score then.
        score = float(a.score) if a.score > 0 else c.score
        picks.append(
            Pick(
                source_id=c.source_id,
                start=start,
                end=end,
                hook=a.hook,
                title=a.title,
                hashtags=a.hashtags,
                keywords=a.keywords,
                credit=credits.get(c.source_id),
                score=score,
                reason=a.reason or "chosen by AI",
                candidate_id=c.id,
                meta={"text": c.text, "ai_score": a.score},
            )
        )
    return picks, usage, notes
