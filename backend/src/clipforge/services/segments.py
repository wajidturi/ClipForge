"""Short video segments for rendering: only [start, end] of a source, cached on disk.

Links: downloaded with yt-dlp's range download (never the whole video).
Files: cut from the uploaded original with FFmpeg.
Times are always full-video times, even when the source was ingested with a window.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select

from clipforge.core import ffmpeg
from clipforge.core.config import get_settings
from clipforge.db.enums import AssetKind, AssetOwner, Platform
from clipforge.db.models import MediaAsset, Source
from clipforge.db.session import get_sessionmaker
from clipforge.jobs.registry import PermanentJobError
from clipforge.services import ingest
from clipforge.services.sources import original_file, source_dir


def segment_name(start_s: float, end_s: float) -> str:
    return f"seg_{start_s:010.2f}_{end_s:010.2f}".replace(".", "p")


def ensure_segment(
    source_id: uuid.UUID,
    start_s: float,
    end_s: float,
    *,
    is_cancelled: Callable[[], bool] | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> MediaAsset:
    if end_s <= start_s:
        raise PermanentJobError("segment end must be after start")
    settings = get_settings()
    stem = segment_name(start_s, end_s)
    out_dir = source_dir(settings, source_id) / "segments"
    with get_sessionmaker()() as s:
        src = s.get(Source, source_id)
        if src is None:
            raise PermanentJobError("source was deleted")
        if src.duration_s and start_s >= src.duration_s:
            raise PermanentJobError("segment starts after the end of the video")
        rel = (out_dir / f"{stem}.mp4").relative_to(settings.resolved_data_dir).as_posix()
        cached = s.scalar(
            select(MediaAsset).where(
                MediaAsset.owner_type == AssetOwner.source,
                MediaAsset.owner_id == source_id,
                MediaAsset.kind == AssetKind.segment,
                MediaAsset.path == rel,
            )
        )
        if cached and (settings.resolved_data_dir / cached.path).exists():
            s.expunge(cached)
            return cached
        url, platform, original = src.url, src.platform, original_file(settings, src)

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{stem}.mp4"
    if platform == Platform.file:
        if original is None:
            raise PermanentJobError("the uploaded file is missing")
        ffmpeg.cut_segment(original, target, start_s, end_s, is_cancelled=is_cancelled)
        path: Path = target
    else:
        path = ingest.make_downloader(settings).download_section(
            url, out_dir, start_s, end_s, stem=stem, progress=progress, is_cancelled=is_cancelled
        )
        if path.suffix != ".mp4":
            path = path.rename(target)

    with get_sessionmaker()() as s:
        asset = MediaAsset(
            owner_type=AssetOwner.source,
            owner_id=source_id,
            kind=AssetKind.segment,
            path="",
        )
        info = ffmpeg.probe(path)
        v = info.video
        asset.path = path.relative_to(settings.resolved_data_dir).as_posix()
        asset.bytes = path.stat().st_size
        asset.duration_s = info.duration_s
        asset.width = v.width if v else None
        asset.height = v.height if v else None
        asset.codec = v.codec_name if v else None
        s.add(asset)
        s.commit()
        s.refresh(asset)
        s.expunge(asset)
        return asset
