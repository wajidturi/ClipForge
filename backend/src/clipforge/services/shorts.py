"""Editing, reviewing and listing Shorts (the library, the review queue, the studio).

Status flow (see docs/04-architecture.md):

    picked -> rendering -> review -> approved
                       \\-> failed     \\-> rejected
    approved/rejected -> review (re-open)   any -> dropped (from a run page)

Edits are allowed whenever the Short is not rendering or dropped; a change that
affects the picture (times, hook, keywords, captions) needs a new render, which
creates a new version and puts the Short back into review.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from clipforge.core.config import get_settings
from clipforge.db.enums import JobStatus, QcVerdict, ShortStatus, SourceStatus
from clipforge.db.models import (
    Job,
    QcReport,
    Run,
    Short,
    ShortPart,
    ShortVersion,
    Source,
    Transcript,
)
from clipforge.pipeline.selection.validate import clean_hashtags, clean_hook, clean_title, snap
from clipforge.services.runs import load_sentences

EDITABLE = {
    ShortStatus.picked,
    ShortStatus.review,
    ShortStatus.approved,
    ShortStatus.rejected,
    ShortStatus.failed,
}
HIDDEN = (ShortStatus.dropped,)
ReviewAction = Literal["approve", "reject", "reopen"]


class ShortStateError(ValueError):
    pass


class ShortInputError(ValueError):
    pass


# ------------------------------------------------------------------ edits
def clean_keywords(words: list[str]) -> list[str]:
    out: list[str] = []
    for w in words:
        k = re.sub(r"\s+", " ", w).strip().upper()
        if k and k not in out:
            out.append(k[:30])
    return out[:3]


def apply_patch(db: Session, short: Short, patch: dict[str, Any]) -> set[str]:
    """Apply field edits; returns the names of the fields that changed.

    Times snap outwards to whole sentences so a Short never starts mid-word.
    """
    if short.status not in EDITABLE:
        raise ShortStateError(
            "this Short is rendering right now"
            if short.status == ShortStatus.rendering
            else f"a {short.status.value} Short cannot be edited"
        )
    changed: set[str] = set()

    def put(name: str, value: Any) -> None:
        if getattr(short, name) != value:
            setattr(short, name, value)
            changed.add(name)

    if patch.get("hook") is not None:
        put("hook", clean_hook(patch["hook"]))
    if patch.get("title") is not None:
        put("title", clean_title(patch["title"]))
    if patch.get("hashtags") is not None:
        put("hashtags", clean_hashtags(patch["hashtags"]))
    if patch.get("keywords") is not None:
        put("keywords", clean_keywords(patch["keywords"]))
    if patch.get("start_s") is not None or patch.get("end_s") is not None:
        part = db.scalar(
            select(ShortPart).where(ShortPart.short_id == short.id).order_by(ShortPart.idx)
        )
        if part is None:
            raise ShortInputError("this Short has no time range")
        start = part.start_s if patch.get("start_s") is None else float(patch["start_s"])
        end = part.end_s if patch.get("end_s") is None else float(patch["end_s"])
        sents = load_sentences(db, short.source_id)
        ij = snap(sents, start, end)
        if ij is None:
            raise ShortInputError("end must be after start, inside the transcript")
        new = (sents[ij[0]].start, sents[ij[1]].end)
        if new[1] - new[0] > 180:
            raise ShortInputError("a Short can be at most 3 minutes long")
        if (part.start_s, part.end_s) != new:
            part.start_s, part.end_s = new
            changed.add("range")
    return changed


PICTURE_FIELDS = {"hook", "keywords", "range"}  # these change the rendered video


# ------------------------------------------------------------------ review
def review(short: Short, action: ReviewAction, reason: str | None = None) -> None:
    has_render = short.active_version_id is not None
    if action == "approve":
        if not has_render:
            raise ShortStateError("render this Short before approving it")
        if short.status not in (ShortStatus.review, ShortStatus.rejected, ShortStatus.failed):
            raise ShortStateError(f"a {short.status.value} Short cannot be approved")
        short.status = ShortStatus.approved
        short.reject_reason = None
    elif action == "reject":
        if short.status in (ShortStatus.rendering, ShortStatus.dropped):
            raise ShortStateError(f"a {short.status.value} Short cannot be rejected")
        short.status = ShortStatus.rejected
        short.reject_reason = (reason or "").strip()[:500] or None
    else:  # reopen
        if short.status not in (ShortStatus.approved, ShortStatus.rejected):
            raise ShortStateError("only approved or rejected Shorts can be re-opened")
        short.status = ShortStatus.review if has_render else ShortStatus.picked
        short.reject_reason = None


# ------------------------------------------------------------------ library
@dataclass
class LibraryQuery:
    status: list[ShortStatus] | None = None
    run_id: uuid.UUID | None = None
    source_id: uuid.UUID | None = None
    qc: QcVerdict | None = None
    q: str | None = None
    cursor: uuid.UUID | None = None
    limit: int = 30


def _filtered(query: LibraryQuery) -> Select[Short]:
    stmt = select(Short).where(Short.deleted_at.is_(None))
    if query.status:
        stmt = stmt.where(Short.status.in_(query.status))
    else:
        stmt = stmt.where(Short.status.not_in(HIDDEN))
    if query.run_id:
        stmt = stmt.where(Short.run_id == query.run_id)
    if query.source_id:
        stmt = stmt.where(Short.source_id == query.source_id)
    if query.qc:
        stmt = stmt.join(QcReport, QcReport.short_version_id == Short.active_version_id).where(
            QcReport.verdict == query.qc
        )
    if query.q and query.q.strip():
        like = f"%{query.q.strip()}%"
        stmt = stmt.where(
            or_(Short.hook.ilike(like), Short.title.ilike(like), Short.credit.ilike(like))
        )
    return stmt


def library(db: Session, query: LibraryQuery) -> tuple[list[Short], uuid.UUID | None, int]:
    """Newest first, keyset-paginated by id (UUIDv7 ids sort by creation time)."""
    base = _filtered(query)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    page = base
    if query.cursor:
        page = page.where(Short.id < query.cursor)
    rows = list(db.scalars(page.order_by(Short.id.desc()).limit(query.limit + 1)))
    nxt = rows[query.limit - 1].id if len(rows) > query.limit else None
    return rows[: query.limit], nxt, total


def source_titles(db: Session, source_ids: set[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    if not source_ids:
        return {}
    return {
        i: t
        for i, t in db.execute(select(Source.id, Source.title).where(Source.id.in_(source_ids)))
    }


# ------------------------------------------------------------------ dashboard
def stats(db: Session) -> dict[str, Any]:
    def by_status(model: Any, col: Any) -> dict[str, int]:
        return {
            (k.value if hasattr(k, "value") else str(k)): int(n)
            for k, n in db.execute(select(col, func.count()).select_from(model).group_by(col))
        }

    sources = by_status(Source, Source.status)
    shorts = by_status(Short, Short.status)
    shorts.pop(ShortStatus.dropped.value, None)
    qc = {
        v.value: int(n)
        for v, n in db.execute(
            select(QcReport.verdict, func.count())
            .join(Short, Short.active_version_id == QcReport.short_version_id)
            .where(Short.status.not_in(HIDDEN))
            .group_by(QcReport.verdict)
        )
    }
    return {
        "sources": sources,
        "sources_ready": sources.get(SourceStatus.ready.value, 0),
        "shorts": shorts,
        "qc": qc,
        "runs": db.scalar(select(func.count()).select_from(Run)) or 0,
        "renders": db.scalar(select(func.count()).select_from(ShortVersion)) or 0,
        "active_jobs": db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.status.in_([JobStatus.queued, JobStatus.running]))
        )
        or 0,
    }


# ------------------------------------------------------------------ studio
def words_view(db: Session, short: Short, context_s: float = 90.0) -> dict[str, Any]:
    """Words of the Short's range (for caption fixes) and nearby sentences (for trimming)."""
    part = db.scalar(
        select(ShortPart).where(ShortPart.short_id == short.id).order_by(ShortPart.idx)
    )
    tr = db.scalar(select(Transcript).where(Transcript.source_id == short.source_id))
    if part is None or tr is None:
        raise ShortInputError("the source has no transcript")
    data = json.loads((get_settings().resolved_data_dir / tr.words_path).read_text("utf-8"))
    overrides: dict[str, str] = {}
    if short.active_version_id:
        ver = db.get(ShortVersion, short.active_version_id)
        overrides = dict(ver.caption_overrides or {}) if ver else {}
    words = []
    for w in data["words"]:
        start, end, text = float(w[0]), float(w[1]), str(w[2]).strip()
        if end <= part.start_s or start >= part.end_s:
            continue
        key = f"{start:.2f}"
        words.append(
            {"key": key, "start": start, "end": end, "text": text, "override": overrides.get(key)}
        )
    sents = load_sentences(db, short.source_id)
    context = [
        {
            "start": s.start,
            "end": s.end,
            "text": s.text,
            "heat": s.heat,
            "inside": s.end > part.start_s + 0.05 and s.start < part.end_s - 0.05,
        }
        for s in sents
        if s.end > part.start_s - context_s and s.start < part.end_s + context_s
    ]
    return {
        "start_s": part.start_s,
        "end_s": part.end_s,
        "words": words,
        "overrides": overrides,
        "sentences": context,
    }
