"""Export rendered Shorts as ready-to-post ZIP files.

One Short -> ``<slug>.zip`` with the video, cover, extra sizes and ``post.txt``
(title, caption, hashtags and a credit line with a timestamped link to the original).
A run -> one folder per Short plus ``shorts.csv`` (handy for bulk schedulers).

MP4/JPEG are already compressed, so they are stored, not deflated (fast).
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from clipforge.core.config import get_settings
from clipforge.db.enums import AssetKind, AssetOwner, Platform, ShortStatus
from clipforge.db.models import MediaAsset, QcReport, Short, ShortPart, Source
from clipforge.pipeline.ingest.timewin import format_time

FILES = {
    AssetKind.mp4: "short.mp4",
    AssetKind.cover: "cover.jpg",
    AssetKind.aspect_4x5: "short-4x5.mp4",
    AssetKind.aspect_1x1: "short-1x1.mp4",
}


class ExportError(ValueError):
    pass


def slug(text: str | None, fallback: str = "short") -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:60].rstrip("-") or fallback


def link_at(src: Source, t: float) -> str:
    """Link to the original at second `t` (YouTube/Twitch understand a time parameter)."""
    if src.platform == Platform.file:
        return ""
    sec = max(0, int(t))
    parts = urlsplit(src.url)
    if src.platform == Platform.youtube:
        q = [(k, v) for k, v in parse_qsl(parts.query) if k != "t"] + [("t", f"{sec}s")]
        return urlunsplit(parts._replace(query=urlencode(q)))
    if src.platform == Platform.twitch:
        h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
        q = [(k, v) for k, v in parse_qsl(parts.query) if k != "t"] + [("t", f"{h}h{m}m{s}s")]
        return urlunsplit(parts._replace(query=urlencode(q)))
    return src.url


def post_text(short: Short, src: Source, start_s: float) -> str:
    tags = " ".join(short.hashtags or [])
    title = short.title or (short.hook or "").capitalize()
    lines = [
        "TITLE",
        title,
        "",
        "CAPTION",
        f"{short.hook or title}\n\n{tags}".strip(),
        "",
        "HASHTAGS",
        tags,
    ]
    credit = short.credit or src.channel_name
    link = link_at(src, start_s)
    if credit or link:
        where = f" ({format_time(start_s)} in the original)" if link else ""
        lines += ["", "CREDIT", f"Clip from {credit or 'the original'}{where}", link]
    return "\n".join(lines).rstrip() + "\n"


@dataclass
class _Item:
    short: Short
    src: Source
    start: float
    end: float
    assets: list[MediaAsset]
    qc: str | None


def _items(db: Session, shorts: list[Short]) -> list[_Item]:
    vids = [s.active_version_id for s in shorts if s.active_version_id]
    assets: dict[uuid.UUID, list[MediaAsset]] = {}
    for a in db.scalars(
        select(MediaAsset).where(
            MediaAsset.owner_type == AssetOwner.short_version,
            MediaAsset.owner_id.in_(vids),
            MediaAsset.kind.in_(list(FILES)),
        )
    ):
        assets.setdefault(a.owner_id, []).append(a)
    qcs = {
        q.short_version_id: q.verdict.value
        for q in db.scalars(select(QcReport).where(QcReport.short_version_id.in_(vids)))
    }
    out = []
    for s in shorts:
        vid = s.active_version_id
        if not vid or not any(a.kind == AssetKind.mp4 for a in assets.get(vid, [])):
            continue
        src = db.get(Source, s.source_id)
        part = db.scalar(
            select(ShortPart).where(ShortPart.short_id == s.id).order_by(ShortPart.idx)
        )
        if src is None or part is None:
            continue
        out.append(_Item(s, src, part.start_s, part.end_s, assets[vid], qcs.get(vid)))
    return out


def _write(z: zipfile.ZipFile, root: Path, prefix: str, it: _Item) -> str:
    video = ""
    for a in it.assets:
        p = root / a.path
        if p.exists():
            name = prefix + FILES[a.kind]
            z.write(p, name, compress_type=zipfile.ZIP_STORED)
            if a.kind == AssetKind.mp4:
                video = name
    z.writestr(prefix + "post.txt", post_text(it.short, it.src, it.start))
    return video


def export_short(db: Session, short: Short, dest_dir: Path) -> Path:
    items = _items(db, [short])
    if not items:
        raise ExportError("this Short has no rendered video yet")
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{slug(short.title or short.hook)}-{uuid.uuid4().hex[:6]}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        _write(z, get_settings().resolved_data_dir, "", items[0])
    return path


def export_many(db: Session, shorts: list[Short], dest_dir: Path, name: str) -> Path:
    items = _items(db, shorts)
    if not items:
        raise ExportError("none of these Shorts has a rendered video")
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{slug(name, 'shorts')}-{uuid.uuid4().hex[:6]}.zip"
    root = get_settings().resolved_data_dir
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["n", "folder", "video", "title", "hook", "hashtags", "seconds", "qc", "status"])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, it in enumerate(items, 1):
            folder = f"{n:02d}-{slug(it.short.title or it.short.hook)}/"
            video = _write(z, root, folder, it)
            w.writerow(
                [
                    n,
                    folder.rstrip("/"),
                    video,
                    it.short.title or "",
                    it.short.hook or "",
                    " ".join(it.short.hashtags or []),
                    round(it.end - it.start, 1),
                    it.qc or "",
                    it.short.status.value,
                ]
            )
        z.writestr("shorts.csv", buf.getvalue())
    return path


EXPORTABLE = (ShortStatus.review, ShortStatus.approved)
