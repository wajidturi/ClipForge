"""The *cut*: the slow, template-independent half of a render, cached on disk.

segment -> EDL edit (pauses out) -> face/facecam/motion analysis -> loudness ->
browser preview proxy. Stored in ``renders/<short>/cuts/<key>/`` where the key
hashes the source, the range and the EDL, so any number of re-renders with other
templates, captions or stickers reuse it and only run the fast compose stage.

``cut.json`` holds everything the compose stage and the studio's live preview
need: source size, duration, facecam box, per-sample tracking targets, scene cuts,
zoom peaks, loudness, caption words (output time, with their stable keys) and a
suggested reaction phrase.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete

from clipforge.core import ffmpeg
from clipforge.core.config import get_settings
from clipforge.core.hashing import sha256_file
from clipforge.db.enums import AssetKind, AssetOwner
from clipforge.db.models import MediaAsset
from clipforge.db.session import get_sessionmaker
from clipforge.jobs.registry import JobContext
from clipforge.pipeline.render import compose, reframe
from clipforge.pipeline.render.edl import CaptionWord, build_edl, keyed_words
from clipforge.pipeline.render.effects import audio_chain, measure_loudness, pick_peaks
from clipforge.pipeline.render.reframe import Box
from clipforge.pipeline.render.scene_render import CutPlan
from clipforge.pipeline.signals import vision as vision_sig
from clipforge.services import segments

CUT_VERSION = 1
KEEP_CUTS = 2
PAD_S = 2.0
REACTIONS = [
    "oh my god",
    "oh my gosh",
    "no way",
    "let's go",
    "lets go",
    "what the",
    "holy",
    "are you kidding",
    "insane",
    "unbelievable",
    "bro",
    "wow",
    "yes",
    "what",
]


@dataclass
class Cut:
    key: str
    dir: Path
    edited: Path
    preview: Path
    data: dict[str, Any]

    @property
    def plan(self) -> CutPlan:
        d = self.data
        cam = Box(*d["cam"]) if d.get("cam") else None
        return CutPlan(
            d["src_w"],
            d["src_h"],
            d["duration"],
            cam,
            [(t, x) for t, x in d["targets"]],
            d["cuts"],
            d["zoom_peaks"],
            d.get("measured"),
        )

    def keyed(self) -> list[tuple[CaptionWord, str]]:
        return [(CaptionWord(a, b, t), k) for a, b, t, k in self.data["words"]]


def cut_key(source_id: uuid.UUID, start: float, end: float, edl_json: list[Any]) -> str:
    raw = json.dumps([str(source_id), round(start, 3), round(end, 3), edl_json, CUT_VERSION])
    return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:16]


def cuts_root(short_id: uuid.UUID) -> Path:
    return get_settings().resolved_data_dir / "renders" / str(short_id) / "cuts"


def load_cut(short_id: uuid.UUID, key: str) -> Cut | None:
    d = cuts_root(short_id) / key
    meta = d / "cut.json"
    if not (meta.exists() and (d / "edited.mkv").exists() and (d / "preview.mp4").exists()):
        return None
    return Cut(key, d, d / "edited.mkv", d / "preview.mp4", json.loads(meta.read_text("utf-8")))


def find_reaction(words: list[CaptionWord], near: float | None) -> str | None:
    """A short exclamation the streamer actually said ("NO WAY!"), closest to the peak."""
    text = [(w.start, re.sub(r"[^\w' ]", "", w.text.lower()).strip()) for w in words]
    found: list[tuple[float, str]] = []
    for i, (t, _) in enumerate(text):
        window = " ".join(x for _, x in text[i : i + 4])
        for phrase in REACTIONS:
            if window.startswith(phrase + " ") or window == phrase:
                found.append((t, phrase))
                break
    if not found:
        return None
    t, phrase = min(found, key=lambda f: abs(f[0] - (near if near is not None else f[0])))
    return phrase.upper().replace("LETS", "LET'S") + "!"


def ensure_cut(job: JobContext, info: dict[str, Any], start: float, end: float) -> Cut:
    short_id = info["short"]["id"]
    source_id = info["short"]["source_id"]
    edl = build_edl(info["words"], start, end)
    key = cut_key(source_id, start, end, edl.to_json())
    if (hit := load_cut(short_id, key)) is not None:
        job.progress(40, "reusing the prepared cut")
        return hit
    settings = get_settings()
    d = cuts_root(short_id) / key
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)

    job.progress(2, "fetching the video for this moment")
    seg_start = max(0.0, start - PAD_S)
    seg = segments.ensure_segment(
        source_id,
        seg_start,
        end + PAD_S,
        is_cancelled=lambda: job.cancelled,
        progress=lambda p, st: job.progress(None if p < 0 else 2 + p * 0.18, st),
    )
    job.check_cancelled()
    edited = d / "edited.mkv"
    job.progress(22, "cutting pauses")
    compose.edit_pass(
        settings.resolved_data_dir / seg.path,
        seg_start,
        edl,
        edited,
        is_cancelled=lambda: job.cancelled,
    )
    job.progress(30, "finding faces and the facecam")
    try:
        face_model: Path | None = vision_sig.ensure_face_model(
            settings.resolved_data_dir / "models"
        )
    except Exception:
        face_model = None
    a = reframe.analyze(edited, face_model=face_model)
    cam = reframe.detect_cam(a.samples)
    job.check_cancelled()
    peaks_src = ([info["hottest"]] if info["hottest"] is not None else []) + info["loud"]
    zoom_peaks = pick_peaks([edl.map_clamped(t) for t in peaks_src], edl.duration)
    job.progress(36, "measuring loudness")
    measured = measure_loudness(edited)
    preview = d / "preview.mp4"
    job.progress(38, "preparing the editor preview")
    ffmpeg.run_ffmpeg(
        [
            "-i",
            str(edited),
            "-vf",
            "scale='min(960,iw)':-2,fps=30",
            "-af",
            audio_chain(measured),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "26",
            "-g",
            "15",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(preview),
        ],
        duration_s=edl.duration,
        is_cancelled=lambda: job.cancelled,
    )
    keyed = keyed_words(info["words"], edl)
    data = {
        "v": CUT_VERSION,
        "range": [start, end],
        "src_w": a.width,
        "src_h": a.height,
        "duration": edl.duration,
        "cam": [cam.x, cam.y, cam.w, cam.h] if cam else None,
        # follow targets with the facecam masked out (gaming: follow the action)
        "targets": reframe.sample_targets(a, cam),
        "cuts": a.cuts,
        "zoom_peaks": zoom_peaks,
        "measured": measured,
        "words": [[w.start, w.end, w.text, k] for w, k in keyed],
        "reaction": find_reaction([w for w, _ in keyed], zoom_peaks[0] if zoom_peaks else None),
        "preview_asset_id": None,
    }
    data["preview_asset_id"] = str(_register_preview(short_id, preview, edl.duration))
    (d / "cut.json").write_text(json.dumps(data), encoding="utf-8")
    _prune(short_id, keep=key)
    return Cut(key, d, edited, preview, data)


def _register_preview(short_id: uuid.UUID, path: Path, duration: float) -> uuid.UUID:
    root = get_settings().resolved_data_dir
    info = ffmpeg.probe(path)
    with get_sessionmaker()() as s:
        a = MediaAsset(
            owner_type=AssetOwner.short,
            owner_id=short_id,
            kind=AssetKind.proxy,
            path=path.relative_to(root).as_posix(),
            bytes=path.stat().st_size,
            sha256=sha256_file(path),
            duration_s=info.duration_s or duration,
            width=info.video.width if info.video else None,
            height=info.video.height if info.video else None,
            codec=info.video.codec_name if info.video else None,
        )
        s.add(a)
        s.commit()
        return a.id


def _prune(short_id: uuid.UUID, keep: str) -> None:
    """Keep the newest few cuts per Short (the intermediate files are large)."""
    root = cuts_root(short_id)
    dirs = sorted(
        (p for p in root.iterdir() if p.is_dir() and p.name != keep),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    data_root = get_settings().resolved_data_dir
    for old in dirs[KEEP_CUTS - 1 :]:
        rel = (old / "preview.mp4").relative_to(data_root).as_posix()
        with get_sessionmaker()() as s:
            s.execute(
                delete(MediaAsset).where(
                    MediaAsset.owner_type == AssetOwner.short, MediaAsset.path == rel
                )
            )
            s.commit()
        shutil.rmtree(old, ignore_errors=True)
