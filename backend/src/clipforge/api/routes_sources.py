from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import or_, select
from starlette.concurrency import run_in_threadpool

from clipforge.api.deps import DB, Config
from clipforge.api.schemas import (
    AnalyzeRequest,
    AssetOut,
    PlatformOut,
    SegmentOut,
    SourceCreate,
    SourceCreated,
    SourceDeleted,
    SourceDetail,
    SourceOut,
    SourcePage,
    TimelineOut,
    TranscriptOut,
)
from clipforge.db.enums import AssetOwner, Platform, SourceStatus
from clipforge.db.models import MediaAsset, Source
from clipforge.pipeline.ingest.resolver import InvalidSourceError
from clipforge.pipeline.ingest.timewin import InvalidTimeError, make_window
from clipforge.services import sources as svc
from clipforge.services import timeline as timeline_svc

router = APIRouter(prefix="/sources", tags=["sources"])

PLATFORMS = [
    (Platform.youtube, "YouTube", "https://www.youtube.com/watch?v=…"),
    (Platform.twitch, "Twitch", "https://www.twitch.tv/videos/…"),
    (Platform.kick, "Kick", "https://kick.com/<channel>/videos/…"),
    (Platform.tiktok, "TikTok", "https://www.tiktok.com/@user/video/…"),
    (Platform.x, "X / Twitter", "https://x.com/user/status/…"),
    (Platform.instagram, "Instagram", "https://www.instagram.com/reel/…"),
    (Platform.facebook, "Facebook", "https://www.facebook.com/watch/?v=…"),
    (Platform.rumble, "Rumble", "https://rumble.com/v…-title.html"),
    (Platform.vimeo, "Vimeo", "https://vimeo.com/…"),
    (Platform.reddit, "Reddit", "https://www.reddit.com/r/…/comments/…"),
    (Platform.dailymotion, "Dailymotion", "https://www.dailymotion.com/video/…"),
]


def _bad_request(e: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))


def _get(db: DB, source_id: uuid.UUID) -> Source:
    src = db.get(Source, source_id)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    return src


@router.get("/platforms", response_model=list[PlatformOut])
def platforms() -> list[PlatformOut]:
    return [PlatformOut(id=p, name=n, example=e) for p, n, e in PLATFORMS]


@router.post("", response_model=SourceCreated, status_code=status.HTTP_201_CREATED)
def add_source(body: SourceCreate, db: DB, response: Response) -> SourceCreated:
    try:
        window = make_window(body.start, body.end)
        r = svc.create_from_url(db, body.url, window)
    except (InvalidSourceError, InvalidTimeError) as e:
        raise _bad_request(e) from None
    if not r.created:
        response.status_code = status.HTTP_200_OK
    return SourceCreated(
        source=SourceOut.model_validate(r.source),
        created=r.created,
        job_id=r.job.id if r.job else None,
    )


@router.post("/upload", response_model=SourceCreated, status_code=status.HTTP_201_CREATED)
async def upload_source(
    db: DB,
    settings: Config,
    response: Response,
    file: Annotated[UploadFile, File(description="video or audio file")],
    start: Annotated[str | None, Form()] = None,
    end: Annotated[str | None, Form()] = None,
) -> SourceCreated:
    try:
        window = make_window(start, end)
        r = await run_in_threadpool(
            svc.create_from_upload, db, settings, file.filename or "", file.file, window
        )
    except (InvalidSourceError, InvalidTimeError) as e:
        raise _bad_request(e) from None
    except svc.UploadTooLargeError as e:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(e)) from None
    if not r.created:
        response.status_code = status.HTTP_200_OK
    return SourceCreated(
        source=SourceOut.model_validate(r.source),
        created=r.created,
        job_id=r.job.id if r.job else None,
    )


@router.get("", response_model=SourcePage)
def list_sources(
    db: DB,
    status_: Annotated[SourceStatus | None, Query(alias="status")] = None,
    platform: Platform | None = None,
    q: Annotated[str | None, Query(max_length=200, description="search title/channel")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[uuid.UUID | None, Query(description="id of the last item seen")] = None,
) -> SourcePage:
    stmt = select(Source).order_by(Source.id.desc()).limit(limit + 1)
    if status_:
        stmt = stmt.where(Source.status == status_)
    if platform:
        stmt = stmt.where(Source.platform == platform)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Source.title.ilike(like), Source.channel_name.ilike(like)))
    if cursor:
        stmt = stmt.where(Source.id < cursor)
    rows = list(db.scalars(stmt).all())
    more = len(rows) > limit
    rows = rows[:limit]
    return SourcePage(
        items=[SourceOut.model_validate(r) for r in rows],
        next_cursor=str(rows[-1].id) if more and rows else None,
    )


@router.get("/{source_id}", response_model=SourceDetail)
def get_source(source_id: uuid.UUID, db: DB) -> SourceDetail:
    src = _get(db, source_id)
    assets = db.scalars(
        select(MediaAsset)
        .where(MediaAsset.owner_type == AssetOwner.source, MediaAsset.owner_id == source_id)
        .order_by(MediaAsset.created_at)
    ).all()
    meta = src.meta or {}
    return SourceDetail(
        **SourceOut.model_validate(src).model_dump(),
        assets=[AssetOut.model_validate(a) for a in assets],
        chapters=meta.get("chapters") or [],
        has_heatmap=bool(meta.get("heatmap")),
    )


@router.get("/{source_id}/transcript", response_model=TranscriptOut)
def get_transcript(source_id: uuid.UUID, db: DB) -> TranscriptOut:
    _get(db, source_id)
    tr, segs = timeline_svc.transcript_for(db, source_id)
    if tr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no transcript yet")
    return TranscriptOut(
        language=tr.language,
        language_prob=tr.language_prob,
        model=tr.model,
        device=tr.device,
        word_count=tr.word_count,
        segments=[SegmentOut.model_validate(s) for s in segs],
    )


@router.get("/{source_id}/timeline", response_model=TimelineOut)
def get_timeline(
    source_id: uuid.UUID,
    db: DB,
    settings: Config,
    bins: Annotated[int, Query(ge=20, le=2000)] = 400,
) -> TimelineOut:
    src = _get(db, source_id)
    return TimelineOut(**timeline_svc.build_timeline(db, settings, src, bins))


@router.post("/{source_id}/analyze", response_model=SourceCreated)
def analyze_source(source_id: uuid.UUID, body: AnalyzeRequest, db: DB) -> SourceCreated:
    src = _get(db, source_id)
    if src.status in (SourceStatus.new, SourceStatus.downloading, SourceStatus.analyzing):
        raise HTTPException(status.HTTP_409_CONFLICT, "this source is still being processed")
    if not svc.has_audio(db, src):
        raise HTTPException(status.HTTP_409_CONFLICT, "the audio is not downloaded yet")
    job = svc.enqueue_analyze(db, src, body.model_dump(exclude_none=True))
    db.commit()
    return SourceCreated(source=SourceOut.model_validate(src), created=False, job_id=job.id)


@router.post("/{source_id}/retry", response_model=SourceCreated)
def retry_source(source_id: uuid.UUID, db: DB) -> SourceCreated:
    src = _get(db, source_id)
    if src.status in (SourceStatus.new, SourceStatus.downloading, SourceStatus.analyzing):
        raise HTTPException(status.HTTP_409_CONFLICT, "this source is still being processed")
    job = svc.retry(db, src)
    return SourceCreated(source=SourceOut.model_validate(src), created=False, job_id=job.id)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: uuid.UUID, db: DB, settings: Config, request: Request) -> Response:
    src = _get(db, source_id)
    svc.delete(db, settings, src)
    request.app.state.hub.publish_model(SourceDeleted(id=source_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
