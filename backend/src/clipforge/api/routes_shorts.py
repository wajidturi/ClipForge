"""Library, review queue, export, dashboard stats and the Short studio (words, AI edit)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from starlette.background import BackgroundTask

from clipforge.ai.registry import make_provider
from clipforge.api.deps import DB, Config
from clipforge.api.routes_runs import get_short_or_404, shorts_out
from clipforge.api.schemas import (
    AIEditRequest,
    BulkReviewOut,
    BulkReviewRequest,
    BulkSkip,
    EditApplied,
    EditOut,
    ReviewRequest,
    ShortOut,
    ShortPage,
    ShortWords,
    StatsOut,
)
from clipforge.core.config import Settings
from clipforge.db.enums import QcVerdict, ShortStatus
from clipforge.db.models import EditRequest, Run, Short
from clipforge.services import ai_edit, settings_store
from clipforge.services import export as export_svc
from clipforge.services import shorts as shorts_svc

router = APIRouter(tags=["shorts"])


@router.get("/shorts", response_model=ShortPage)
def list_shorts(
    db: DB,
    status_: Annotated[list[ShortStatus] | None, Query(alias="status")] = None,
    run_id: uuid.UUID | None = None,
    source_id: uuid.UUID | None = None,
    qc: QcVerdict | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> ShortPage:
    """The Shorts library, newest first. Dropped picks are hidden unless asked for."""
    rows, nxt, total = shorts_svc.library(
        db,
        shorts_svc.LibraryQuery(
            status=status_,
            run_id=run_id,
            source_id=source_id,
            qc=qc,
            q=q,
            cursor=cursor,
            limit=limit,
        ),
    )
    return ShortPage(items=shorts_out(db, rows), next_cursor=nxt, total=total)


@router.get("/stats", response_model=StatsOut)
def get_stats(db: DB) -> StatsOut:
    return StatsOut(**shorts_svc.stats(db))


# ------------------------------------------------------------------ review
@router.post("/shorts/{short_id}/review", response_model=ShortOut)
def review_short(short_id: uuid.UUID, body: ReviewRequest, db: DB) -> ShortOut:
    short = get_short_or_404(db, short_id)
    try:
        shorts_svc.review(short, body.action, body.reason)
    except shorts_svc.ShortStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    db.commit()
    return shorts_out(db, [short])[0]


@router.post("/shorts/review", response_model=BulkReviewOut)
def review_many(body: BulkReviewRequest, db: DB) -> BulkReviewOut:
    """Approve/reject/re-open several Shorts; ones in the wrong state are skipped."""
    found = {s.id: s for s in db.scalars(select(Short).where(Short.id.in_(body.short_ids)))}
    updated: list[uuid.UUID] = []
    skipped: list[BulkSkip] = []
    for sid in dict.fromkeys(body.short_ids):
        short = found.get(sid)
        if short is None or short.deleted_at is not None:
            skipped.append(BulkSkip(id=sid, reason="not found"))
            continue
        try:
            shorts_svc.review(short, body.action, body.reason)
            updated.append(sid)
        except shorts_svc.ShortStateError as e:
            skipped.append(BulkSkip(id=sid, reason=str(e)))
    db.commit()
    return BulkReviewOut(updated=updated, skipped=skipped)


# ------------------------------------------------------------------ export
def _exports_dir(settings: Settings) -> Path:
    return settings.resolved_data_dir / "tmp" / "exports"


def _send_zip(path: Path) -> FileResponse:
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name.rsplit("-", 1)[0] + ".zip",
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@router.get("/shorts/{short_id}/export.zip", response_class=FileResponse)
def export_short(short_id: uuid.UUID, db: DB, settings: Config) -> FileResponse:
    """Video, cover, extra sizes and post.txt (title, caption, hashtags, credit)."""
    short = get_short_or_404(db, short_id)
    try:
        path = export_svc.export_short(db, short, _exports_dir(settings))
    except export_svc.ExportError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    return _send_zip(path)


@router.get("/runs/{run_id}/export.zip", response_class=FileResponse)
def export_run(
    run_id: uuid.UUID,
    db: DB,
    settings: Config,
    only: Annotated[str, Query(pattern="^(approved|rendered)$")] = "approved",
) -> FileResponse:
    """All approved (or all rendered: approved + in review) Shorts of a run."""
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    states = [ShortStatus.approved] if only == "approved" else list(export_svc.EXPORTABLE)
    rows = list(
        db.scalars(
            select(Short)
            .where(Short.run_id == run_id, Short.status.in_(states), Short.deleted_at.is_(None))
            .order_by(Short.score.desc())
        )
    )
    try:
        path = export_svc.export_many(db, rows, _exports_dir(settings), f"run-{run.id.hex[-6:]}")
    except export_svc.ExportError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    return _send_zip(path)


# ------------------------------------------------------------------ studio
@router.get("/shorts/{short_id}/words", response_model=ShortWords)
def short_words(short_id: uuid.UUID, db: DB) -> ShortWords:
    """Words in the Short (caption fixes) and the sentences around it (trimming)."""
    short = get_short_or_404(db, short_id)
    try:
        return ShortWords(**shorts_svc.words_view(db, short))
    except shorts_svc.ShortInputError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None


@router.post("/shorts/{short_id}/ai-edit", response_model=EditOut)
def plan_ai_edit(short_id: uuid.UUID, body: AIEditRequest, db: DB) -> EditOut:
    """Ask the AI for an edit plan. Nothing changes until the plan is applied."""
    short = get_short_or_404(db, short_id)
    provider = make_provider(settings_store.effective(db))
    try:
        er = ai_edit.plan(db, short, body.instruction, provider)
    except shorts_svc.ShortStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    return EditOut.model_validate(er)


@router.get("/shorts/{short_id}/edits", response_model=list[EditOut])
def list_edits(short_id: uuid.UUID, db: DB) -> list[EditOut]:
    get_short_or_404(db, short_id)
    rows = db.scalars(
        select(EditRequest)
        .where(EditRequest.short_id == short_id)
        .order_by(EditRequest.id.desc())
        .limit(30)
    )
    return [EditOut.model_validate(r) for r in rows]


@router.post("/edits/{edit_id}/apply", response_model=EditApplied)
def apply_edit(edit_id: uuid.UUID, db: DB) -> EditApplied:
    er = db.get(EditRequest, edit_id)
    if er is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "edit not found")
    try:
        job = ai_edit.apply(db, er)
    except shorts_svc.ShortStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    except shorts_svc.ShortInputError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    short = get_short_or_404(db, er.short_id)
    return EditApplied(
        edit=EditOut.model_validate(er),
        short=shorts_out(db, [short])[0],
        job_id=job.id if job else None,
    )
