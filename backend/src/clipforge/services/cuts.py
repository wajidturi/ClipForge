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

import functools
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
from clipforge.core.logging import get_logger
from clipforge.db.enums import AssetKind, AssetOwner
from clipforge.db.models import MediaAsset
from clipforge.db.session import get_sessionmaker
from clipforge.jobs.registry import JobContext
from clipforge.pipeline.render import camhd, compose, matte, reframe
from clipforge.pipeline.render.edl import CaptionWord, build_edl, keyed_words
from clipforge.pipeline.render.effects import audio_chain, measure_loudness, pick_peaks
from clipforge.pipeline.render.reframe import Box
from clipforge.pipeline.render.scene_render import CutPlan
from clipforge.pipeline.signals import vision as vision_sig
from clipforge.services import segments

log = get_logger(__name__)
CUT_VERSION = 4  # 2: 1080p preview; 3: every person / facecam; 4: person cut-out (matte)
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
        cams, primary, kind = cam_boxes(d)
        return CutPlan(
            d["src_w"],
            d["src_h"],
            d["duration"],
            cams[primary],
            [(t, x) for t, x in d["targets"]],
            d["cuts"],
            d["zoom_peaks"],
            d.get("measured"),
            cams=cams,
            cam_kind=kind,
            matte=self.dir / "matte.mp4" if d.get("matte") else None,
            matte_size=tuple(d["matte"]["size"]) if d.get("matte") else (0, 0),
            camhd=[
                (self.dir / e["file"], camhd.HDRegion(*e["region"], *e["size"])) if e else None
                for e in d.get("camhd") or []
            ],
        )

    def keyed(self) -> list[tuple[CaptionWord, str]]:
        return [(CaptionWord(a, b, t), k) for a, b, t, k in self.data["words"]]


def cam_boxes(d: dict[str, Any]) -> tuple[list[Box], int, str]:
    """What a facecam panel shows: (boxes left to right, main one, kind).

    kind: ``overlay`` (streamer facecams), ``camera`` (people on the main camera) or
    ``action`` (nobody found: a close-up of the action, so every template still works).
    Cuts made before v3 only know one facecam box."""
    if d.get("cams"):
        cams = [Box(*b) for b in d["cams"]]
        return cams, min(int(d.get("primary") or 0), len(cams) - 1), d.get("cam_kind") or "overlay"
    if d.get("cam"):
        return [Box(*d["cam"])], 0, "overlay"
    targets = [(t, x) for t, x in d.get("targets") or []]
    return [reframe.action_box(targets)], 0, "action"


def has_people(d: dict[str, Any]) -> bool:
    return cam_boxes(d)[2] != "action"


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
        ensure_camhd(job, hit)  # cuts made before the HD facecam get it now
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
    people = reframe.find_people(a.samples)
    cam = people.cams[people.primary] if people.kind == "overlay" else None
    job.check_cancelled()
    peaks_src = ([info["hottest"]] if info["hottest"] is not None else []) + info["loud"]
    zoom_peaks = pick_peaks([edl.map_clamped(t) for t in peaks_src], edl.duration)
    matte_info = _make_matte(job, edited, d / "matte.mp4", people, a)
    job.check_cancelled()
    job.progress(36, "measuring loudness")
    measured = measure_loudness(edited)
    preview = d / "preview.mp4"
    job.progress(38, "preparing the editor preview")
    ffmpeg.run_ffmpeg(
        [
            "-i",
            str(edited),
            "-vf",
            "scale='min(1920,iw)':-2,fps=30",  # 1080p for 16:9
            "-af",
            audio_chain(measured),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
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
        "cams": [[b.x, b.y, b.w, b.h] for b in people.cams],
        "cam_kind": people.kind if people.cams else "none",
        "primary": people.primary,
        # gaming: follow the action with the facecams masked out; people on camera:
        # keep the group in the shot, or follow whoever is talking
        "targets": reframe.sample_targets(a, people),
        "cuts": a.cuts,
        "zoom_peaks": zoom_peaks,
        "measured": measured,
        "words": [[w.start, w.end, w.text, k] for w, k in keyed],
        "reaction": find_reaction([w for w, _ in keyed], zoom_peaks[0] if zoom_peaks else None),
        "preview_asset_id": None,
    }
    data["preview_asset_id"] = str(_register_preview(short_id, preview, edl.duration))
    if matte_info is not None:
        matte_info["asset_id"] = str(_register_preview(short_id, d / "matte.mp4", edl.duration))
    data["matte"] = matte_info
    (d / "cut.json").write_text(json.dumps(data), encoding="utf-8")
    _prune(short_id, keep=key)
    cut = Cut(key, d, edited, preview, data)
    ensure_camhd(job, cut)
    return cut


def _hd_progress(job: JobContext, label: str, pct: float) -> None:
    job.progress(40, f"{label}: {pct:.0f}%")


def ensure_camhd(job: JobContext, cut: Cut) -> None:
    """Upscale small streamer facecams with the AI upscaler (camhd.py), once per cut.
    Optional like the matte: without the model or a usable runtime the renderer crops
    the source as before."""
    d = cut.data
    if "camhd" in d:
        return
    cams, _, kind = cam_boxes(d)
    regions = camhd.hd_regions(cams, d["src_w"], d["src_h"]) if kind == "overlay" else []
    entries: list[dict[str, Any] | None] = [None] * len(regions)
    if any(regions):
        try:
            model = camhd.ensure_model(get_settings().resolved_data_dir / "models")
            up = camhd.Upscaler(model)
        except Exception as e:
            log.warning("cut.camhd_unavailable", error=str(e)[:200])
            up = None
        todo = [(i, r) for i, r in enumerate(regions) if r is not None]
        for n, (i, r) in enumerate(todo if up is not None else []):
            assert up is not None
            label = "making the streamer HD" + (f" ({n + 1}/{len(todo)})" if len(todo) > 1 else "")
            job.progress(40, label)
            out = cut.dir / f"camhd{i}.mp4"
            try:
                camhd.build_hd(
                    cut.edited,
                    r,
                    out,
                    duration=d["duration"],
                    upscaler=up,
                    is_cancelled=lambda: job.cancelled,
                    on_progress=functools.partial(_hd_progress, job, label),
                )
            except ffmpeg.FFmpegCancelledError:
                raise
            except Exception as e:  # a sharper cam is a nice-to-have, never a failed render
                log.warning("cut.camhd_failed", error=str(e)[:300])
                out.unlink(missing_ok=True)
                continue
            entries[i] = {
                "file": out.name,
                "region": [r.x, r.y, r.w, r.h],
                "size": [r.out_w, r.out_h],
            }
            log.info("cut.camhd", region=[r.w, r.h], size=[r.out_w, r.out_h], gpu=up.on_gpu)
    d["camhd"] = entries
    (cut.dir / "cut.json").write_text(json.dumps(d), encoding="utf-8")


def _make_matte(
    job: JobContext, edited: Path, out: Path, people: reframe.People, a: reframe.Analysis
) -> dict[str, Any] | None:
    """Cut the streamer(s) out of the facecam panel, so templates can swap the
    background. Optional: without the model (offline) the original cam is used."""
    if people.kind not in ("overlay", "camera") or not people.cams:
        return None
    settings = get_settings()
    try:
        model = vision_sig.ensure_segment_model(settings.resolved_data_dir / "models")
    except Exception as e:
        log.warning("cut.matte_model_unavailable", error=str(e)[:200])
        return None
    job.progress(33, "cutting out the streamer")
    try:
        w, h = matte.build_matte(
            edited,
            people.cams,
            out,
            src_w=a.width,
            src_h=a.height,
            duration=a.duration,
            make_segmenter=lambda: matte.MediaPipeSegmenter(model),
            is_cancelled=lambda: job.cancelled,
            on_progress=lambda p: job.progress(33 + p * 0.03, "cutting out the streamer"),
        )
    except ffmpeg.FFmpegCancelledError:
        raise
    except Exception as e:  # a background swap is a nice-to-have, never a failed render
        log.warning("cut.matte_failed", error=str(e)[:300])
        out.unlink(missing_ok=True)
        return None
    return {"size": [w, h], "asset_id": None}


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
        rels = [(old / f).relative_to(data_root).as_posix() for f in ("preview.mp4", "matte.mp4")]
        with get_sessionmaker()() as s:
            s.execute(
                delete(MediaAsset).where(
                    MediaAsset.owner_type == AssetOwner.short, MediaAsset.path.in_(rels)
                )
            )
            s.commit()
        shutil.rmtree(old, ignore_errors=True)
