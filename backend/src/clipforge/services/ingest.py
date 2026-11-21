"""The `source.ingest` job: from a link or file to analysable audio on disk.

Link:  metadata (yt-dlp) -> checks (live? too long?) -> window -> audio-only download
File:  probe (ffprobe) -> checks (has audio?) -> window -> audio extraction
Both:  register MediaAssets, mark the source ready. Phase 3 continues with transcription.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from clipforge.core import ffmpeg
from clipforge.core.config import Settings, get_settings
from clipforge.core.hashing import sha256_file
from clipforge.core.logging import get_logger
from clipforge.db.enums import AssetKind, AssetOwner, Platform, SourceStatus
from clipforge.db.models import MediaAsset, Source
from clipforge.db.session import get_sessionmaker
from clipforge.jobs.registry import JobCancelledError, JobContext, PermanentJobError
from clipforge.pipeline.ingest import errors
from clipforge.pipeline.ingest.downloader import Downloader, DownloadError, RemoteInfo
from clipforge.pipeline.ingest.resolver import InvalidSourceError
from clipforge.pipeline.ingest.timewin import (
    InvalidTimeError,
    Window,
    default_window,
    format_time,
)
from clipforge.services.sources import original_file, source_dir

log = get_logger(__name__)


def make_downloader(settings: Settings) -> Downloader:
    """Factory (patched in tests to avoid the network)."""
    return Downloader(
        retries=settings.ytdlp_retries,
        socket_timeout=settings.ytdlp_socket_timeout,
        cookies_browser=settings.ytdlp_cookies_browser,
    )


class _Progress:
    """Maps a sub-step's 0..100 onto a slice of the job's progress bar."""

    def __init__(self, ctx: JobContext) -> None:
        self.ctx = ctx

    def slice(self, lo: float, hi: float) -> Any:
        def report(pct: float, step: str | None = None) -> None:
            self.ctx.progress(None if pct < 0 else lo + (hi - lo) * pct / 100, step)

        return report


def _update(source_id: uuid.UUID, **values: Any) -> None:
    with get_sessionmaker()() as s:
        src = s.get(Source, source_id)
        if src is None:
            raise PermanentJobError("source was deleted")
        for k, v in values.items():
            setattr(src, k, v)
        s.commit()


def _add_asset(s: Session, source_id: uuid.UUID, kind: AssetKind, path: Path) -> MediaAsset:
    info = ffmpeg.probe(path)
    v = info.video
    # Re-ingesting replaces the previous asset of the same kind.
    for old in s.scalars(
        select(MediaAsset).where(
            MediaAsset.owner_type == AssetOwner.source,
            MediaAsset.owner_id == source_id,
            MediaAsset.kind == kind,
        )
    ):
        s.delete(old)
    asset = MediaAsset(
        owner_type=AssetOwner.source,
        owner_id=source_id,
        kind=kind,
        path=str(path.relative_to(get_settings().resolved_data_dir).as_posix()),
        bytes=path.stat().st_size,
        sha256=sha256_file(path),
        duration_s=info.duration_s,
        width=v.width if v else None,
        height=v.height if v else None,
        codec=(v.codec_name if v else next((x.codec_name for x in info.streams), None)),
    )
    s.add(asset)
    return asset


def _pick_window(
    src: Source, duration_s: float | None, settings: Settings
) -> tuple[Window | None, str | None]:
    """Explicit window (clamped) or, for over-long sources, the last N hours."""
    if src.window_start_s is not None or src.window_end_s is not None:
        w = Window(src.window_start_s or 0.0, src.window_end_s).clamp(duration_s)
        return w, None
    auto = default_window(duration_s, settings.max_source_hours, settings.default_window_hours)
    if auto:
        note = (
            f"Video is {format_time(duration_s or 0)} long; using the last "
            f"{settings.default_window_hours:g} h ({format_time(auto.start_s)}-"
            f"{format_time(auto.end_s or 0)}). Set a window to choose another part."
        )
        return auto, note
    return None, None


# ------------------------------------------------------------------------ link
def _ingest_url(ctx: JobContext, src_id: uuid.UUID, settings: Settings) -> dict[str, Any]:
    with get_sessionmaker()() as s:
        src = s.get(Source, src_id)
        assert src is not None
        url, platform = src.url, src.platform
    p = _Progress(ctx)
    dl = make_downloader(settings)
    ctx.progress(2, "reading video information")
    info: RemoteInfo = dl.fetch_info(url, platform)
    ctx.check_cancelled()
    if info.is_live:
        raise PermanentJobError(
            "This is a live stream. Live clipping is a separate feature (Live page); "
            "add the link again after the stream has ended to clip the recording."
        )

    with get_sessionmaker()() as s:
        src = s.get(Source, src_id)
        assert src is not None
        # The offline resolver may have guessed the id; yt-dlp's id is authoritative.
        if src.external_id != info.id and info.platform != Platform.other:
            dup = s.scalar(
                select(Source).where(
                    Source.platform == info.platform,
                    Source.external_id == info.id,
                    Source.id != src_id,
                )
            )
            if dup is not None:
                src.status = SourceStatus.skipped
                src.skip_reason = f"same video as source {dup.id}"
                s.commit()
                return {"skipped": "duplicate", "duplicate_of": str(dup.id)}
            src.platform, src.external_id = info.platform, info.id
        src.title = (info.title or src.title or "")[:500] or None
        src.channel_name = (info.channel or "")[:200] or None
        src.duration_s = info.duration_s
        src.published_at = info.published_at
        src.language = info.language
        if info.webpage_url:
            src.url = info.webpage_url[:2000]
        try:
            window, note = _pick_window(src, info.duration_s, settings)
        except InvalidTimeError as e:
            raise PermanentJobError(str(e)) from None
        src.window_start_s = window.start_s if window else None
        src.window_end_s = window.end_s if window else None
        src.meta = {**(src.meta or {}), **info.meta(), "window_note": note}
        s.commit()

    ctx.progress(5, "downloading audio")
    out = source_dir(settings, src_id)
    audio = dl.download_audio(
        url, out, window, progress=p.slice(5, 92), is_cancelled=lambda: ctx.cancelled
    )
    ctx.check_cancelled()
    ctx.progress(95, "checking the download")
    check_window_alignment(audio, window)
    with get_sessionmaker()() as s:
        asset = _add_asset(s, src_id, AssetKind.audio, audio)
        s.commit()
        return {"audio_asset_id": str(asset.id), "duration_s": asset.duration_s}


ALIGN_TOLERANCE_S = 1.5


def check_window_alignment(audio: Path, window: Window | None) -> None:
    """A windowed download must be as long as the window; a longer file means the cut
    started early and all later timestamps would be wrong. Fail loudly instead."""
    if window is None or window.end_s is None:
        return
    got = ffmpeg.probe(audio).duration_s
    want = window.end_s - window.start_s
    if got is not None and got > want + ALIGN_TOLERANCE_S:
        raise DownloadError(
            f"downloaded part is {got:.1f}s but the window is {want:.1f}s; times would be "
            "misaligned. Update the downloader (clipforge update-downloader) and retry."
        )


# ------------------------------------------------------------------------ file
def _ingest_file(ctx: JobContext, src_id: uuid.UUID, settings: Settings) -> dict[str, Any]:
    with get_sessionmaker()() as s:
        src = s.get(Source, src_id)
        assert src is not None
        original = original_file(settings, src)
    if original is None:
        raise PermanentJobError("the uploaded file is missing; add it again")
    ctx.progress(3, "reading the file")
    try:
        info = ffmpeg.probe(original)
    except ffmpeg.FFmpegError as e:
        raise PermanentJobError(f"This file could not be read as video or audio ({e}).") from None
    if not info.has_audio:
        raise PermanentJobError("This file has no audio track; Shorts are cut from speech.")
    with get_sessionmaker()() as s:
        src = s.get(Source, src_id)
        assert src is not None
        src.duration_s = info.duration_s
        try:
            window, note = _pick_window(src, info.duration_s, settings)
        except InvalidTimeError as e:
            raise PermanentJobError(str(e)) from None
        src.window_start_s = window.start_s if window else None
        src.window_end_s = window.end_s if window else None
        src.meta = {**(src.meta or {}), "window_note": note, "format": info.format_name}
        if info.has_video:  # keep the original as the video asset (renders cut from it)
            _add_asset(s, src_id, AssetKind.video, original)
        s.commit()

    ctx.progress(8, "extracting audio")
    audio = source_dir(settings, src_id) / "audio.m4a"
    p = _Progress(ctx)
    ffmpeg.extract_audio(
        original,
        audio,
        start_s=window.start_s if window else None,
        end_s=window.end_s if window else None,
        duration_s=info.duration_s,
        on_progress=p.slice(8, 95),
        is_cancelled=lambda: ctx.cancelled,
    )
    with get_sessionmaker()() as s:
        asset = _add_asset(s, src_id, AssetKind.audio, audio)
        s.commit()
        return {"audio_asset_id": str(asset.id), "duration_s": asset.duration_s}


# ------------------------------------------------------------------------ entry
def ingest(ctx: JobContext, source_id: uuid.UUID) -> dict[str, Any]:
    settings = get_settings()
    with get_sessionmaker()() as s:
        src = s.get(Source, source_id)
        if src is None:
            raise PermanentJobError("source was deleted")
        is_file = src.platform == Platform.file
    _update(source_id, status=SourceStatus.downloading, error=None, error_hint=None)
    try:
        result = (_ingest_file if is_file else _ingest_url)(ctx, source_id, settings)
    except (JobCancelledError, ffmpeg.FFmpegCancelledError):
        _update(source_id, status=SourceStatus.failed, error="Cancelled", error_hint=None)
        raise JobCancelledError from None
    except PermanentJobError as e:
        _update(source_id, status=SourceStatus.failed, error=str(e), error_hint=None)
        raise
    except (DownloadError, InvalidSourceError, ffmpeg.FFmpegError) as e:
        if ctx.cancelled:  # yt-dlp reports a cancel as an error
            _update(source_id, status=SourceStatus.failed, error="Cancelled", error_hint=None)
            raise JobCancelledError from None
        ex = errors.explain(str(e))
        final = not ex.retryable or ctx.is_last_attempt
        _update(
            source_id,
            status=SourceStatus.failed if final else SourceStatus.downloading,
            error=ex.message,
            error_hint=ex.hint,
        )
        if not ex.retryable:
            raise PermanentJobError(f"{ex.message} {ex.hint or ''}".strip()) from None
        raise RuntimeError(ex.message) from e
    except Exception as e:
        if ctx.is_last_attempt:
            _update(source_id, status=SourceStatus.failed, error=str(e)[:500])
        raise
    if not result.get("skipped"):
        # Next stage: transcript + signals (runs on an `ml` worker).
        from clipforge.services.sources import enqueue_analyze

        with get_sessionmaker()() as s:
            src = s.get(Source, source_id)
            if src is not None:
                result["analyze_job_id"] = str(enqueue_analyze(s, src).id)
                s.commit()
    log.info("source.ingested", source_id=str(source_id), **result)
    return result
