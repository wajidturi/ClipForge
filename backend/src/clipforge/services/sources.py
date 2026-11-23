"""Creating, listing and deleting sources (the long videos Shorts are cut from)."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from clipforge.core.config import Settings
from clipforge.core.ids import uuid7
from clipforge.db.enums import AssetKind, JobStatus, Platform, SourceStatus
from clipforge.db.models import Job, MediaAsset, Short, ShortVersion, Source
from clipforge.jobs import queue
from clipforge.pipeline.ingest.resolver import InvalidSourceError, resolve_url
from clipforge.pipeline.ingest.timewin import Window

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".flv", ".ts", ".wmv"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus", ".flac"}
INGEST_JOB = "source.ingest"


class UploadTooLargeError(ValueError):
    pass


@dataclass
class CreateResult:
    source: Source
    created: bool  # False = this video was already added
    job: Job | None


def source_dir(settings: Settings, source_id: uuid.UUID) -> Path:
    return settings.resolved_data_dir / "sources" / str(source_id)


def _enqueue_ingest(db: Session, src: Source) -> Job:
    caps = ("cpu",) if src.platform == Platform.file else ("cpu", "net")
    label = src.title or (src.url if src.platform != Platform.file else "Uploaded file")
    job = queue.enqueue(
        db,
        INGEST_JOB,
        {"source_id": str(src.id)},
        label=f"Add source: {label[:120]}",
        caps=caps,
        subject=("source", src.id),
        max_attempts=3,
    )
    src.latest_job_id = job.id
    src.status = SourceStatus.new
    src.error = src.error_hint = None
    return job


ANALYZE_JOB = "source.analyze"


def enqueue_analyze(db: Session, src: Source, options: dict[str, object] | None = None) -> Job:
    """Transcript + signals. Needs an `ml` worker (one by default keeps GPU memory safe)."""
    job = queue.enqueue(
        db,
        ANALYZE_JOB,
        {"source_id": str(src.id), "options": options or {}},
        label=f"Analyze: {(src.title or src.url)[:120]}",
        caps=("cpu", "net", "ml"),
        subject=("source", src.id),
        max_attempts=2,
    )
    src.latest_job_id = job.id
    src.status = SourceStatus.analyzing
    src.error = src.error_hint = None
    return job


def has_audio(db: Session, src: Source) -> bool:
    return (
        db.scalar(
            select(MediaAsset.id).where(
                MediaAsset.owner_id == src.id, MediaAsset.kind == AssetKind.audio
            )
        )
        is not None
    )


def _find(db: Session, platform: Platform, external_id: str) -> Source | None:
    return db.scalar(
        select(Source).where(Source.platform == platform, Source.external_id == external_id)
    )


def create_from_url(db: Session, url: str, window: Window | None) -> CreateResult:
    r = resolve_url(url)
    existing = _find(db, r.platform, r.external_id)
    if existing is not None:
        if existing.status == SourceStatus.failed:
            if window:
                existing.window_start_s, existing.window_end_s = window.start_s, window.end_s
            job = _enqueue_ingest(db, existing)
            db.commit()
            return CreateResult(existing, False, job)
        return CreateResult(existing, False, None)
    src = Source(
        id=uuid7(),
        platform=r.platform,
        external_id=r.external_id,
        url=r.url,
        window_start_s=window.start_s if window else None,
        window_end_s=window.end_s if window else None,
    )
    db.add(src)
    db.flush()
    job = _enqueue_ingest(db, src)
    db.commit()
    return CreateResult(src, True, job)


def create_from_upload(
    db: Session,
    settings: Settings,
    filename: str,
    stream: BinaryIO,
    window: Window | None,
) -> CreateResult:
    ext = Path(filename or "").suffix.lower()
    if ext not in VIDEO_EXT | AUDIO_EXT:
        raise InvalidSourceError(
            f"'{ext or 'no extension'}' is not a supported video or audio file "
            f"({', '.join(sorted(VIDEO_EXT | AUDIO_EXT))})"
        )
    incoming = settings.resolved_data_dir / "sources" / "_incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    tmp = incoming / f"{uuid.uuid4().hex}{ext}"
    limit = settings.max_upload_mb * 1024 * 1024
    h = hashlib.sha256()
    size = 0
    try:
        with tmp.open("wb") as out:
            while block := stream.read(1 << 20):
                size += len(block)
                if size > limit:
                    raise UploadTooLargeError(f"file is larger than {settings.max_upload_mb} MB")
                h.update(block)
                out.write(block)
        if size == 0:
            raise InvalidSourceError("the file is empty")
        digest = h.hexdigest()
        existing = _find(db, Platform.file, digest[:32])
        if existing is not None:
            tmp.unlink()
            return CreateResult(existing, False, None)
        src = Source(
            id=uuid7(),
            platform=Platform.file,
            external_id=digest[:32],
            url=f"file:{Path(filename).name}",
            title=Path(filename).stem[:500],
            window_start_s=window.start_s if window else None,
            window_end_s=window.end_s if window else None,
            meta={"original_name": Path(filename).name, "sha256": digest, "bytes": size},
        )
        dest = source_dir(settings, src.id) / f"original{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(tmp, dest)
        db.add(src)
        db.flush()
        job = _enqueue_ingest(db, src)
        db.commit()
        return CreateResult(src, True, job)
    finally:
        tmp.unlink(missing_ok=True)


def original_file(settings: Settings, src: Source) -> Path | None:
    files = list(source_dir(settings, src.id).glob("original.*"))
    return files[0] if files else None


def retry(db: Session, src: Source) -> Job:
    """Re-run only what failed: analysis if the audio is already on disk, else ingest."""
    job = enqueue_analyze(db, src) if has_audio(db, src) else _enqueue_ingest(db, src)
    db.commit()
    return job


def delete(db: Session, settings: Settings, src: Source) -> None:
    """Cancel its jobs, remove its files and rows (assets, transcripts, signals...)."""
    for job in db.scalars(
        select(Job).where(
            Job.subject_type == "source",
            Job.subject_id == src.id,
            Job.status.in_([JobStatus.queued, JobStatus.running]),
        )
    ):
        queue.request_cancel(db, job.id)
    # Shorts cut from this source go with it: their renders, cached cuts and previews.
    short_ids = list(db.scalars(select(Short.id).where(Short.source_id == src.id)))
    version_ids = (
        list(db.scalars(select(ShortVersion.id).where(ShortVersion.short_id.in_(short_ids))))
        if short_ids
        else []
    )
    db.query(MediaAsset).filter(MediaAsset.owner_id.in_([src.id, *short_ids, *version_ids])).delete(
        synchronize_session=False
    )
    db.delete(src)
    db.commit()
    shutil.rmtree(source_dir(settings, src.id), ignore_errors=True)
    for sid in short_ids:
        shutil.rmtree(settings.resolved_data_dir / "renders" / str(sid), ignore_errors=True)
