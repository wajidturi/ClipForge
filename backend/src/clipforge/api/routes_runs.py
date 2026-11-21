from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from clipforge.ai.ollama import OllamaProvider
from clipforge.api.deps import DB, Config
from clipforge.api.schemas import (
    ActiveVersion,
    AIStatusOut,
    CandidateOut,
    OptionOut,
    RenderOptions,
    RenderQueued,
    RenderRequest,
    RunCreate,
    RunDetail,
    RunOut,
    RunRenderRequest,
    ShortDetail,
    ShortOut,
    ShortPartOut,
    ShortPatch,
    VersionOut,
)
from clipforge.db.enums import AssetKind, AssetOwner, ShortStatus
from clipforge.db.models import Candidate, Job, MediaAsset, Run, Short, ShortPart, ShortVersion
from clipforge.pipeline.render import captions, compose
from clipforge.pipeline.selection.validate import clean_hashtags, clean_hook, clean_title, snap
from clipforge.services import preview as preview_svc
from clipforge.services import runs as runs_svc
from clipforge.services import versions as versions_svc

router = APIRouter(tags=["runs"])


def _shorts_out(db: DB, shorts: list[Short]) -> list[ShortOut]:
    if not shorts:
        return []
    ids = [s.id for s in shorts]
    parts: dict[uuid.UUID, list[ShortPartOut]] = {}
    for p in db.scalars(
        select(ShortPart).where(ShortPart.short_id.in_(ids)).order_by(ShortPart.idx)
    ):
        parts.setdefault(p.short_id, []).append(ShortPartOut.model_validate(p))
    with_video = set(
        db.scalars(
            select(MediaAsset.owner_id).where(
                MediaAsset.owner_type == AssetOwner.source,
                MediaAsset.owner_id.in_({s.source_id for s in shorts}),
                MediaAsset.kind.in_([AssetKind.proxy, AssetKind.video]),
            )
        )
    )
    active = versions_svc.version_dicts(
        db, [s.active_version_id for s in shorts if s.active_version_id]
    )
    jobs = versions_svc.latest_render_jobs(db, ids)
    return [
        ShortOut.model_validate(s).model_copy(
            update={
                "parts": parts.get(s.id, []),
                "has_preview": s.source_id in with_video,
                "active": ActiveVersion(**active[s.active_version_id])
                if s.active_version_id in active
                else None,
                "render_job_id": jobs.get(s.id),
            }
        )
        for s in shorts
    ]


def _get_run(db: DB, run_id: uuid.UUID) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    return run


def _get_short(db: DB, short_id: uuid.UUID) -> Short:
    short = db.get(Short, short_id)
    if short is None or short.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "short not found")
    return short


@router.post("/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
def create_run(body: RunCreate, db: DB) -> RunOut:
    try:
        run, _job = runs_svc.create_run(
            db,
            body.source_ids,
            n=body.n,
            pick_mode=body.pick_mode,
            topic=body.topic,
            ai_model=body.ai_model,
        )
    except runs_svc.RunInputError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    return RunOut.model_validate(run)


@router.get("/runs", response_model=list[RunOut])
def list_runs(db: DB, limit: Annotated[int, Query(ge=1, le=200)] = 30) -> list[RunOut]:
    rows = db.scalars(select(Run).order_by(Run.id.desc()).limit(limit)).all()
    return [RunOut.model_validate(r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: uuid.UUID, db: DB) -> RunDetail:
    run = _get_run(db, run_id)
    shorts = list(
        db.scalars(
            select(Short)
            .where(Short.run_id == run_id, Short.status != ShortStatus.dropped)
            .order_by(Short.score.desc())
        )
    )
    cands = db.scalars(select(Candidate).where(Candidate.run_id == run_id).order_by(Candidate.rank))
    job_id = db.scalar(select(Job.id).where(Job.run_id == run_id).order_by(Job.id.desc()))
    return RunDetail(
        **RunOut.model_validate(run).model_dump(),
        shorts=_shorts_out(db, shorts),
        candidates=[CandidateOut.model_validate(c) for c in cands],
        job_id=job_id,
    )


@router.patch("/shorts/{short_id}", response_model=ShortOut)
def edit_short(short_id: uuid.UUID, body: ShortPatch, db: DB) -> ShortOut:
    """Edit a pick before rendering. Times snap to whole sentences."""
    short = _get_short(db, short_id)
    if short.status != ShortStatus.picked:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "only picks that are not rendered yet can be edited here"
        )
    if body.hook is not None:
        short.hook = clean_hook(body.hook)
    if body.title is not None:
        short.title = clean_title(body.title)
    if body.hashtags is not None:
        short.hashtags = clean_hashtags(body.hashtags)
    if body.keywords is not None:
        short.keywords = [k.strip().upper() for k in body.keywords if k.strip()][:3]
    if body.start_s is not None or body.end_s is not None:
        part = db.scalar(
            select(ShortPart).where(ShortPart.short_id == short_id).order_by(ShortPart.idx)
        )
        assert part is not None
        start = part.start_s if body.start_s is None else body.start_s
        end = part.end_s if body.end_s is None else body.end_s
        sents = runs_svc.load_sentences(db, short.source_id)
        ij = snap(sents, start, end)
        if ij is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "end must be after start, inside the transcript",
            )
        part.start_s, part.end_s = sents[ij[0]].start, sents[ij[1]].end
    db.commit()
    return _shorts_out(db, [short])[0]


@router.delete("/shorts/{short_id}", status_code=status.HTTP_204_NO_CONTENT)
def drop_short(short_id: uuid.UUID, db: DB) -> None:
    """Drop a pick (kept for history; its time range becomes free again)."""
    short = _get_short(db, short_id)
    short.status = ShortStatus.dropped
    db.commit()


@router.get("/shorts/{short_id}/preview.jpg", response_class=FileResponse)
async def short_preview(short_id: uuid.UUID, db: DB, settings: Config) -> FileResponse:
    _get_short(db, short_id)
    try:
        path = await run_in_threadpool(preview_svc.preview_strip, db, settings, short_id)
    except preview_svc.NoPreviewError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from None
    return FileResponse(path, media_type="image/jpeg")


@router.get("/ai/status", response_model=AIStatusOut)
async def ai_status(settings: Config) -> AIStatusOut:
    if settings.ai_provider == "none":
        return AIStatusOut(
            provider="none",
            model=None,
            ok=True,
            detail="AI is off; picks use signal scores",
            models=[],
        )
    p = OllamaProvider(settings.ollama_model, settings.ollama_url)
    ok, detail = await run_in_threadpool(p.health)
    try:
        models = await run_in_threadpool(p.list_models) if ok or "not installed" in detail else []
    except Exception:
        models = []
    return AIStatusOut(
        provider="ollama", model=settings.ollama_model, ok=ok, detail=detail, models=models
    )


# ------------------------------------------------------------------ rendering
LAYOUT_LABELS = {
    "auto": "Automatic (recommended)",
    "crop": "Follow the subject (9:16 crop)",
    "stack": "Facecam on top, game below",
    "bubble": "Game full screen, round facecam",
    "full": "Whole picture over a blurred background",
}


@router.get("/render/options", response_model=RenderOptions)
async def render_options() -> RenderOptions:
    enc = await run_in_threadpool(compose.video_encoder)
    return RenderOptions(
        styles=[OptionOut(id=k, label=s.label) for k, s in captions.STYLES.items()],
        layouts=[OptionOut(id=k, label=v) for k, v in LAYOUT_LABELS.items()],
        aspects=[
            OptionOut(id="4:5", label="4:5 (Instagram feed)"),
            OptionOut(id="1:1", label="1:1 (square)"),
        ],
        encoder="GPU (NVENC)" if enc[1] == "h264_nvenc" else "CPU (x264)",
    )


@router.get("/shorts/{short_id}", response_model=ShortDetail)
def get_short(short_id: uuid.UUID, db: DB) -> ShortDetail:
    short = _get_short(db, short_id)
    base = _shorts_out(db, [short])[0]
    vids = list(
        db.scalars(
            select(ShortVersion.id)
            .where(ShortVersion.short_id == short_id)
            .order_by(ShortVersion.version_no.desc())
        )
    )
    vd = versions_svc.version_dicts(db, vids)
    return ShortDetail(**base.model_dump(), versions=[VersionOut(**vd[v]) for v in vids if v in vd])


@router.post(
    "/shorts/{short_id}/render", response_model=RenderQueued, status_code=status.HTTP_202_ACCEPTED
)
def render_short(short_id: uuid.UUID, body: RenderRequest, db: DB) -> RenderQueued:
    short = _get_short(db, short_id)
    if body.style and body.style not in captions.STYLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown style '{body.style}'")
    opts = body.model_dump(exclude_none=True)
    if short.active_version_id:
        opts["origin"] = "rerender"
    try:
        job = versions_svc.enqueue_render(db, short, opts)
    except versions_svc.RenderStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    db.commit()
    return RenderQueued(job_ids=[job.id])


@router.post(
    "/runs/{run_id}/render", response_model=RenderQueued, status_code=status.HTTP_202_ACCEPTED
)
def render_run(run_id: uuid.UUID, body: RunRenderRequest, db: DB) -> RenderQueued:
    _get_run(db, run_id)
    if body.style and body.style not in captions.STYLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown style '{body.style}'")
    q = select(Short).where(Short.run_id == run_id, Short.status == ShortStatus.picked)
    if body.short_ids:
        q = q.where(Short.id.in_(body.short_ids))
    opts = body.model_dump(exclude_none=True, exclude={"short_ids"})
    jobs = []
    for short in db.scalars(q):
        try:
            jobs.append(versions_svc.enqueue_render(db, short, opts).id)
        except versions_svc.RenderStateError:
            continue
    db.commit()
    if not jobs:
        raise HTTPException(status.HTTP_409_CONFLICT, "nothing to render: no picks waiting")
    return RenderQueued(job_ids=jobs)
