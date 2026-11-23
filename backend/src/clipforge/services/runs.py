"""Runs: "make N Shorts from these sources".

`create_run` stores the request and queues `run.select`, which:
  1. loads every source's scored sentences
  2. builds candidate windows (skipping ranges already used by earlier Shorts)
  3. picks: no-AI heuristic, or AI (smart = candidate summaries, deep = full text)
     - AI unreachable/invalid -> falls back to the heuristic and says so
     - AI picks fewer than asked -> topped up with the best remaining candidates
  4. validates (whole sentences, speech >= 12 s, <= 90 s, no overlaps, <= 2 per source)
  5. saves candidates and Shorts (status `picked`) for review/rendering
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from clipforge.ai.base import AIError, Usage
from clipforge.ai.registry import make_provider
from clipforge.core.logging import get_logger
from clipforge.db.base import utcnow
from clipforge.db.enums import RunStatus, ShortFormat, ShortStatus, SourceStatus
from clipforge.db.models import (
    Candidate as CandidateRow,
)
from clipforge.db.models import (
    Job,
    Run,
    RunSource,
    Segment,
    Short,
    ShortPart,
    Source,
    Transcript,
)
from clipforge.db.session import get_sessionmaker
from clipforge.jobs import queue
from clipforge.jobs.registry import JobContext, PermanentJobError
from clipforge.pipeline.selection import Candidate, Pick, Sent
from clipforge.pipeline.selection.ai_picker import ai_picks
from clipforge.pipeline.selection.callbacks import find_callbacks
from clipforge.pipeline.selection.heuristic import heuristic_picks
from clipforge.pipeline.selection.validate import validate
from clipforge.pipeline.selection.windows import build_candidates
from clipforge.services import settings_store, versions

log = get_logger(__name__)

PickMode = Literal["free", "smart", "deep"]
SELECT_JOB = "run.select"
INACTIVE = (ShortStatus.rejected, ShortStatus.dropped)


class RunInputError(ValueError):
    pass


def create_run(
    db: Session,
    source_ids: list[uuid.UUID],
    *,
    n: int,
    pick_mode: PickMode,
    topic: str | None = None,
    ai_model: str | None = None,
) -> tuple[Run, Job]:
    if not source_ids:
        raise RunInputError("choose at least one source")
    srcs = db.scalars(select(Source).where(Source.id.in_(source_ids))).all()
    if len(srcs) != len(set(source_ids)):
        raise RunInputError("some sources do not exist")
    not_ready = [s.title or s.url for s in srcs if s.status != SourceStatus.ready]
    if not_ready:
        raise RunInputError(f"not analysed yet: {', '.join(not_ready[:3])}")
    settings = settings_store.effective(db)
    uses_ai = pick_mode != "free" and settings.ai_provider != "none"
    run = Run(
        params={
            "source_ids": [str(s) for s in source_ids],
            "n": n,
            "pick_mode": pick_mode,
            "topic": topic,
        },
        status=RunStatus.queued,
        ai_provider=settings.ai_provider if uses_ai else None,
        ai_model=(ai_model or settings.ollama_model) if uses_ai else None,
    )
    db.add(run)
    db.flush()
    db.add_all(RunSource(run_id=run.id, source_id=s.id) for s in srcs)
    job = queue.enqueue(
        db,
        SELECT_JOB,
        {"run_id": str(run.id)},
        label=f"Pick {n} moment{'s' if n > 1 else ''} ({pick_mode})",
        # AI runs share the GPU with transcription: keep them on the ml worker.
        caps=("cpu", "ml") if uses_ai else ("cpu",),
        run_id=run.id,
        subject=("run", run.id),
        max_attempts=2,
    )
    db.commit()
    return run, job


def _tag_types(tags: list[Any]) -> tuple[str, ...]:
    return tuple(
        sorted({str(t.get("type")) for t in tags if isinstance(t, dict) and t.get("type")})
    )


def load_sentences(s: Session, source_id: uuid.UUID) -> list[Sent]:
    rows = s.execute(
        select(Segment)
        .join(Transcript, Transcript.id == Segment.transcript_id)
        .where(Transcript.source_id == source_id)
        .order_by(Segment.idx)
    ).scalars()
    return [
        Sent(str(source_id), r.idx, r.start_s, r.end_s, r.text, r.heat, _tag_types(r.tags or []))
        for r in rows
    ]


def used_ranges(s: Session, source_ids: list[uuid.UUID]) -> dict[str, list[tuple[float, float]]]:
    rows = s.execute(
        select(Short.source_id, ShortPart.start_s, ShortPart.end_s)
        .join(ShortPart, ShortPart.short_id == Short.id)
        .where(Short.source_id.in_(source_ids), Short.status.not_in(INACTIVE))
    ).all()
    out: dict[str, list[tuple[float, float]]] = {}
    for sid, a, b in rows:
        out.setdefault(str(sid), []).append((a, b))
    return out


def _set_run(run_id: uuid.UUID, **values: Any) -> None:
    with get_sessionmaker()() as s:
        run = s.get(Run, run_id)
        if run is not None:
            for k, v in values.items():
                setattr(run, k, v)
            s.commit()


def select_moments(ctx: JobContext, run_id: uuid.UUID) -> dict[str, Any]:
    settings = settings_store.effective()
    with get_sessionmaker()() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise PermanentJobError("run was deleted")
        params = dict(run.params)
        source_ids = [uuid.UUID(x) for x in params["source_ids"]]
        srcs = {str(x.id): x for x in s.scalars(select(Source).where(Source.id.in_(source_ids)))}
        sents = {str(sid): load_sentences(s, sid) for sid in source_ids}
        used = used_ranges(s, source_ids)
        ai_model = run.ai_model
        run_uses_ai = run.ai_provider is not None
    _set_run(run_id, status=RunStatus.running, started_at=utcnow(), error=None)
    n, mode, topic = int(params["n"]), str(params["pick_mode"]), params.get("topic")
    credits = {sid: (src.channel_name or None) for sid, src in srcs.items()}
    warnings: list[str] = []

    ctx.progress(5, "finding candidate moments")
    k = settings.candidates_k * (2 if mode == "deep" else 1)
    pool: list[Candidate] = []
    for sid, lst in sents.items():
        if not lst:
            warnings.append(f"{srcs[sid].title or sid}: no transcript sentences")
            continue
        pool += build_candidates(lst, k=k, exclude=used.get(sid))
    pool.sort(key=lambda c: -c.score)
    pool = pool[:k]
    for i, c in enumerate(pool, start=1):
        c.id = i
    if not pool:
        _set_run(
            run_id,
            status=RunStatus.failed,
            finished_at=utcnow(),
            error="No usable moments: the sources have too little speech or are all used already.",
        )
        raise PermanentJobError("no candidate moments found")
    ctx.check_cancelled()

    usage = Usage(provider="none", model="heuristic")
    picks: list[Pick]
    provider = make_provider(settings, ai_model) if mode != "free" and run_uses_ai else None
    if provider is None:
        picks = heuristic_picks(pool, n=n, credit_for=credits)
    else:
        ctx.progress(25, f"asking {provider.model} to choose")
        try:
            picks, usage, notes = ai_picks(
                provider,
                pool,
                n=n,
                credits=credits,
                topic=topic,
                deep=mode == "deep",
                timeout=settings.ai_timeout_s,
            )
            warnings += notes
        except AIError as e:
            warnings.append(f"AI unavailable, used signal scores instead: {e}")
            picks = heuristic_picks(pool, n=n, credit_for=credits)
    ctx.check_cancelled()

    ctx.progress(85, "checking the picks")
    accepted, rejected = validate(picks, sents, n=n, used=used)
    if len(accepted) < n:  # top up with the best remaining candidates
        taken = {p.candidate_id for p in accepted}
        extra = heuristic_picks([c for c in pool if c.id not in taken], n=n, credit_for=credits)
        more, more_rej = validate(
            extra,
            sents,
            n=n - len(accepted),
            used={
                sid: used.get(sid, []) + [(p.start, p.end) for p in accepted if p.source_id == sid]
                for sid in sents
            },
        )
        for p in more:
            p.reason = "filled by signal score: " + p.reason
        if more and provider is not None:
            warnings.append(
                f"AI picked {len(accepted)} usable moments; {len(more)} added by signal score"
            )
        accepted += more
        rejected += [r for r in more_rej if not any("enough Shorts" in i for i in r.issues)]

    callbacks = [
        {
            "setup_start": cb.setup.start,
            "setup_text": cb.setup.text,
            "payoff_start": cb.payoff.start,
            "payoff_text": cb.payoff.text,
            "shared": list(cb.shared),
            "gap_s": round(cb.gap_s),
            "score": cb.score,
        }
        for lst in sents.values()
        for cb in find_callbacks(lst, limit=5)
    ]
    created: list[Short] = []
    with get_sessionmaker()() as s:
        s.add_all(
            CandidateRow(
                run_id=run_id,
                source_id=uuid.UUID(c.source_id),
                start_s=c.start,
                end_s=c.end,
                score=c.score,
                tags=c.tags,
                head_text=c.head,
                tail_text=c.tail,
                rank=c.id,
            )
            for c in pool
        )
        for p in accepted:
            short = Short(
                run_id=run_id,
                source_id=uuid.UUID(p.source_id),
                format=ShortFormat.moment,
                hook=p.hook[:120],
                title=p.title[:200],
                hashtags=p.hashtags,
                keywords=p.keywords,
                credit=p.credit,
                score=round(p.score, 1),
                ai_reason=p.reason[:1000],
                status=ShortStatus.picked,
            )
            s.add(short)
            s.flush()
            s.add(ShortPart(short_id=short.id, idx=0, start_s=p.start, end_s=p.end))
            created.append(short)
        if settings.auto_render:  # Settings -> Rendering -> "Render picks automatically"
            for short in created:
                versions.enqueue_render(s, short, {})
        run = s.get(Run, run_id)
        assert run is not None
        run.status = RunStatus.succeeded
        run.finished_at = utcnow()
        run.ai_usage = asdict(usage)
        run.result = {
            "picked": len(accepted),
            "candidates": len(pool),
            "warnings": warnings,
            "rejected": [
                {"start": r.start, "end": r.end, "hook": r.hook, "issues": r.issues}
                for r in rejected
            ][:20],
            "callbacks": callbacks,
        }
        s.commit()
    log.info(
        "run.selected", run_id=str(run_id), picked=len(accepted), mode=mode, warnings=len(warnings)
    )
    return {"picked": len(accepted), "candidates": len(pool), "warnings": warnings}


def fail_run(run_id: uuid.UUID, error: str) -> None:
    _set_run(run_id, status=RunStatus.failed, finished_at=utcnow(), error=error[:1000])
