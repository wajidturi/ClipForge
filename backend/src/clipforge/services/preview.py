"""Preview strip: 4 frames across a pick (start, 1/3, 2/3, end) as one JPEG.

Lets a reviewer drop picks that show a menu, a loading screen or the wrong game
before anything is rendered. Uses the source's 360p proxy (made during picture
analysis) or the uploaded original; links without a proxy have no preview yet.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipforge.core.config import Settings
from clipforge.db.enums import AssetKind, AssetOwner
from clipforge.db.models import MediaAsset, Short, ShortPart, Source

HEIGHT = 180


class NoPreviewError(LookupError):
    pass


def _video_for(db: Session, settings: Settings, src: Source) -> tuple[Path, float]:
    """(file, time offset of the file's 0 s in full-video seconds)."""
    assets = {
        a.kind: a
        for a in db.scalars(
            select(MediaAsset).where(
                MediaAsset.owner_type == AssetOwner.source, MediaAsset.owner_id == src.id
            )
        )
    }
    if AssetKind.proxy in assets:
        return settings.resolved_data_dir / assets[AssetKind.proxy].path, src.window_start_s or 0.0
    if AssetKind.video in assets:
        return settings.resolved_data_dir / assets[AssetKind.video].path, 0.0
    raise NoPreviewError("no video yet for this source (run picture analysis to get previews)")


def frame_times(start: float, end: float, n: int = 4) -> list[float]:
    pad = min(0.5, (end - start) / 10)
    return [start + pad + i * (end - start - 2 * pad) / (n - 1) for i in range(n)]


def preview_strip(db: Session, settings: Settings, short_id: uuid.UUID) -> Path:
    short = db.get(Short, short_id)
    if short is None:
        raise NoPreviewError("short not found")
    part = db.scalar(
        select(ShortPart).where(ShortPart.short_id == short_id).order_by(ShortPart.idx)
    )
    src = db.get(Source, short.source_id)
    if part is None or src is None:
        raise NoPreviewError("short has no range")
    out = (
        settings.resolved_data_dir
        / "previews"
        / f"{short_id}_{part.start_s:.2f}_{part.end_s:.2f}.jpg"
    )
    if out.exists():
        return out
    video, offset = _video_for(db, settings, src)
    cap = cv2.VideoCapture(str(video))
    frames: list[np.ndarray] = []
    try:
        for t in frame_times(part.start_s, part.end_s):
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t - offset) * 1000)
            ok, f = cap.read()
            if not ok:
                f = np.zeros((HEIGHT, int(HEIGHT * 16 / 9), 3), dtype=np.uint8)
            h, w = f.shape[:2]
            frames.append(cv2.resize(f, (int(w * HEIGHT / h), HEIGHT)))
    finally:
        cap.release()
    out.parent.mkdir(parents=True, exist_ok=True)
    gap = np.full((HEIGHT, 4, 3), 20, dtype=np.uint8)
    strip = frames[0]
    for f in frames[1:]:
        strip = np.hstack([strip, gap, f])
    cv2.imwrite(str(out), strip, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return out
