"""The `short.render` job: one pick -> one new ShortVersion (MP4, cover, QC).

Steps: segment (only this range) -> EDL edit -> picture analysis -> layout plan ->
captions + hook -> loudness -> final encode -> cover -> extra aspects -> QC.
A QC FAIL triggers one automatic re-cut (a sentence later at the start, or one more
sentence at the end) before giving up. Versions never overwrite each other.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from clipforge.core import ffmpeg
from clipforge.core.config import get_settings
from clipforge.core.hashing import sha256_file
from clipforge.core.logging import get_logger
from clipforge.db.enums import (
    AssetKind,
    AssetOwner,
    QcVerdict,
    ShortStatus,
    SignalType,
    VersionOrigin,
    VersionStatus,
)
from clipforge.db.models import (
    MediaAsset,
    QcReport,
    Segment,
    Short,
    ShortPart,
    ShortVersion,
    Signal,
    Transcript,
)
from clipforge.db.session import get_sessionmaker
from clipforge.jobs.registry import JobCancelledError, JobContext, PermanentJobError
from clipforge.pipeline.render import captions, compose, cover, qc, reframe
from clipforge.pipeline.render.edl import Edl, build_edl, caption_words
from clipforge.pipeline.render.effects import measure_loudness, pick_peaks
from clipforge.pipeline.signals import vision as vision_sig
from clipforge.pipeline.transcription.sentences import Word
from clipforge.services import segments

log = get_logger(__name__)

PAD_S = 2.0
ASPECTS = {"4:5": (1080, 1350, AssetKind.aspect_4x5), "1:1": (1080, 1080, AssetKind.aspect_1x1)}
DEFAULTS: dict[str, Any] = {"style": captions.DEFAULT_STYLE, "layout": "auto", "aspects": []}


class _Ctx:
    def __init__(self, job: JobContext) -> None:
        self.job = job

    def slice(self, lo: float, hi: float, step: str) -> Any:
        return lambda pct: self.job.progress(lo + (hi - lo) * max(0.0, min(100.0, pct)) / 100, step)


def _load(short_id: uuid.UUID) -> dict[str, Any]:
    settings = get_settings()
    with get_sessionmaker()() as s:
        short = s.get(Short, short_id)
        if short is None or short.deleted_at is not None:
            raise PermanentJobError("this Short was deleted")
        part = s.scalar(
            select(ShortPart).where(ShortPart.short_id == short_id).order_by(ShortPart.idx)
        )
        tr = s.scalar(select(Transcript).where(Transcript.source_id == short.source_id))
        if part is None or tr is None:
            raise PermanentJobError("the source has no transcript; analyse it first")
        loud = s.scalars(
            select(Signal.start_s)
            .where(
                Signal.source_id == short.source_id,
                Signal.type == SignalType.loud,
                Signal.start_s >= part.start_s,
                Signal.start_s <= part.end_s,
            )
            .order_by(Signal.score.desc())
        ).all()
        hottest = s.scalar(
            select(Segment.start_s)
            .where(
                Segment.transcript_id == tr.id,
                Segment.start_s >= part.start_s,
                Segment.end_s <= part.end_s,
            )
            .order_by(Segment.heat.desc())
        )
        sentences = [
            (a, b)
            for a, b in s.execute(
                select(Segment.start_s, Segment.end_s)
                .where(Segment.transcript_id == tr.id)
                .order_by(Segment.idx)
            )
        ]
        next_no = (
            s.scalar(
                select(func.max(ShortVersion.version_no)).where(ShortVersion.short_id == short_id)
            )
            or 0
        ) + 1
        data = json.loads((settings.resolved_data_dir / tr.words_path).read_text(encoding="utf-8"))
        return {
            "short": {
                "id": short.id,
                "source_id": short.source_id,
                "hook": short.hook,
                "keywords": list(short.keywords or []),
            },
            "start": part.start_s,
            "end": part.end_s,
            "loud": list(loud),
            "hottest": hottest,
            "sentences": sentences,
            "next_no": next_no,
            "words": [Word(*w) for w in data["words"]],
        }


def _set_status(short_id: uuid.UUID, status: ShortStatus, **extra: Any) -> None:
    with get_sessionmaker()() as s:
        short = s.get(Short, short_id)
        if short is not None:
            short.status = status
            for k, v in extra.items():
                setattr(short, k, v)
            s.commit()


def _caption_margin(layout: str, plan: compose.Plan) -> int:
    if layout == "stack" and plan.top_h:
        return compose.OUT_H - plan.top_h - 260  # just below the facecam band
    return 520  # lower third, clear of most faces


def render_version(
    job: JobContext,
    info: dict[str, Any],
    start: float,
    end: float,
    opts: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    """Render one version into `out_dir`; returns paths, plan facts and QC."""
    ctx = _Ctx(job)
    settings = get_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()

    job.progress(2, "fetching the video for this moment")
    seg_start = max(0.0, start - PAD_S)
    seg = segments.ensure_segment(
        info["short"]["source_id"],
        seg_start,
        end + PAD_S,
        is_cancelled=lambda: job.cancelled,
        progress=lambda p, st: job.progress(None if p < 0 else 2 + p * 0.18, st),
    )
    job.check_cancelled()

    edl: Edl = build_edl(info["words"], start, end)
    edited = out_dir / "edited.mkv"
    job.progress(22, "cutting pauses")
    compose.edit_pass(
        settings.resolved_data_dir / seg.path,
        seg_start,
        edl,
        edited,
        is_cancelled=lambda: job.cancelled,
    )

    job.progress(32, "finding faces and the facecam")
    try:
        face_model: Path | None = vision_sig.ensure_face_model(
            settings.resolved_data_dir / "models"
        )
    except Exception:
        face_model = None
    a = reframe.analyze(edited, face_model=face_model)
    cam = reframe.detect_cam(a.samples)
    layout = reframe.choose_layout(a, cam, opts.get("layout", "auto"))
    job.check_cancelled()

    plan = compose.Plan(layout, a.width, a.height, edl.duration, cam=cam)
    out_ar = plan.out_w / ((plan.out_h - plan.top_h) if layout == "stack" else plan.out_h)
    win = min(1.0, a.height * out_ar / a.width)
    plan.crop_keys = reframe.track(a, win, cam=cam if layout in ("stack", "bubble") else None)
    peaks_src = ([info["hottest"]] if info["hottest"] is not None else []) + info["loud"]
    plan.zoom_peaks = pick_peaks([edl.map_clamped(t) for t in peaks_src], edl.duration)

    words = caption_words(info["words"], edl)
    style = opts.get("style", captions.DEFAULT_STYLE)
    ass_text = captions.build_ass(
        words,
        style=style,
        keywords=info["short"]["keywords"],
        hook=info["short"]["hook"],
        margin_v=_caption_margin(layout, plan),
        duration=edl.duration,
    )
    ass = out_dir / "captions.ass"
    ass.write_text(ass_text, encoding="utf-8")

    job.progress(40, "measuring loudness")
    measured = measure_loudness(edited)
    final = out_dir / "short.mp4"
    compose.final_pass(
        edited,
        plan,
        final,
        ass=ass,
        measured=measured,
        on_progress=ctx.slice(42, 85, "rendering"),
        is_cancelled=lambda: job.cancelled,
    )

    job.progress(86, "making the cover")
    peak_t = plan.zoom_peaks[0] if plan.zoom_peaks else edl.duration / 2
    frame = compose.extract_frame(final, peak_t + 0.3, out_dir / "frame.jpg")
    cover_path = cover.make_cover(frame, info["short"]["hook"], out_dir / "cover.jpg")
    frame.unlink(missing_ok=True)

    extras: dict[str, Path] = {}
    for aspect in opts.get("aspects") or []:
        if aspect not in ASPECTS:
            continue
        w, h, _kind = ASPECTS[aspect]
        job.progress(88, f"rendering {aspect}")
        eplan = compose.Plan(
            "full" if layout == "full" else "crop",
            a.width,
            a.height,
            edl.duration,
            reframe.track(a, min(1.0, a.height * (w / h) / a.width)),
            None,
            plan.zoom_peaks,
            w,
            h,
        )
        eass = out_dir / f"captions_{w}x{h}.ass"
        eass.write_text(
            captions.build_ass(
                words,
                style=style,
                keywords=info["short"]["keywords"],
                hook=info["short"]["hook"],
                margin_v=int(h * 0.2),
                duration=edl.duration,
                size=(w, h),
            ),
            encoding="utf-8",
        )
        extras[aspect] = out_dir / f"short_{aspect.replace(':', 'x')}.mp4"
        compose.final_pass(
            edited,
            eplan,
            extras[aspect],
            ass=eass,
            measured=measured,
            is_cancelled=lambda: job.cancelled,
        )

    job.progress(94, "quality check")
    result = qc.check(
        final, caption_coverage=captions.coverage(words, ass_text), expected_s=edl.duration
    )
    edited.unlink(missing_ok=True)
    for g in out_dir.glob("*.txt"):
        g.unlink()
    return {
        "final": final,
        "cover": cover_path,
        "ass": ass,
        "extras": extras,
        "qc": result,
        "edl": edl,
        "layout": layout,
        "cam": asdict(cam) if cam else None,
        "zoom_peaks": plan.zoom_peaks,
        "encoder": compose.video_encoder()[1],
        "render_ms": int((time.monotonic() - t0) * 1000),
        "words": len(words),
    }


def _recut(
    info: dict[str, Any], start: float, end: float, reasons: list[str]
) -> tuple[float, float] | None:
    """One sentence later at the start (bad first frame) or one more at the end (too short)."""
    sents = info["sentences"]
    text = " ".join(reasons)
    if "black frame" in text or "blank" in text:
        later = [a for a, _ in sents if a > start + 0.5 and a < end - 10]
        return (later[0], end) if later else None
    if "too short" in text:
        more = [b for a, b in sents if a >= end - 0.05]
        return (start, more[0]) if more else None
    return None


def _save(
    short_id: uuid.UUID,
    version_no: int,
    origin: VersionOrigin,
    opts: dict[str, Any],
    r: dict[str, Any],
    start: float,
    end: float,
) -> uuid.UUID:
    settings = get_settings()
    root = settings.resolved_data_dir

    def asset(kind: AssetKind, p: Path, vid: uuid.UUID) -> MediaAsset:
        info = ffmpeg.probe(p) if p.suffix == ".mp4" else None
        v = info.video if info else None
        return MediaAsset(
            owner_type=AssetOwner.short_version,
            owner_id=vid,
            kind=kind,
            path=p.relative_to(root).as_posix(),
            bytes=p.stat().st_size,
            sha256=sha256_file(p),
            duration_s=info.duration_s if info else None,
            width=v.width if v else None,
            height=v.height if v else None,
            codec=v.codec_name if v else None,
        )

    with get_sessionmaker()() as s:
        ver = ShortVersion(
            short_id=short_id,
            version_no=version_no,
            origin=origin,
            settings={
                **opts,
                "layout_used": r["layout"],
                "cam": r["cam"],
                "zoom_peaks": r["zoom_peaks"],
                "encoder": r["encoder"],
                "range": [start, end],
            },
            edl=r["edl"].to_json(),
            render_ms=r["render_ms"],
            status=VersionStatus.ready,
        )
        s.add(ver)
        s.flush()
        s.add_all(
            [
                asset(AssetKind.mp4, r["final"], ver.id),
                asset(AssetKind.cover, r["cover"], ver.id),
                asset(AssetKind.caption_ass, r["ass"], ver.id),
            ]
        )
        for aspect, p in r["extras"].items():
            s.add(asset(ASPECTS[aspect][2], p, ver.id))
        q = r["qc"]
        s.add(
            QcReport(
                short_version_id=ver.id,
                verdict=QcVerdict(q.verdict),
                checks=q.checks,
                reasons=q.reasons,
            )
        )
        s.commit()
        return ver.id


def render(job: JobContext, short_id: uuid.UUID, options: dict[str, Any]) -> dict[str, Any]:
    opts = {**DEFAULTS, **{k: v for k, v in options.items() if v is not None}}
    if opts["style"] not in captions.STYLES:
        raise PermanentJobError(f"unknown caption style '{opts['style']}'")
    if opts["layout"] not in reframe.LAYOUTS:
        raise PermanentJobError(f"unknown layout '{opts['layout']}'")
    info = _load(short_id)
    _set_status(short_id, ShortStatus.rendering)
    root = get_settings().resolved_data_dir / "renders" / str(short_id)
    start, end = info["start"], info["end"]
    origin = VersionOrigin(options.get("origin", "render"))
    version_no = info["next_no"]
    try:
        out_dir = root / f"v{version_no}"
        r = render_version(job, info, start, end, opts, out_dir)
        vid = _save(short_id, version_no, origin, opts, r, start, end)
        q = r["qc"]
        if q.verdict == "fail" and (cut := _recut(info, start, end, q.reasons)):
            job.progress(5, "QC failed: re-cutting once")
            start, end = cut
            version_no += 1
            out_dir = root / f"v{version_no}"
            r = render_version(job, info, start, end, opts, out_dir)
            vid = _save(short_id, version_no, VersionOrigin.recut, opts, r, start, end)
            q = r["qc"]
        ok = q.verdict != "fail"
        _set_status(
            short_id, ShortStatus.review if ok else ShortStatus.failed, active_version_id=vid
        )
        return {
            "version_id": str(vid),
            "version_no": version_no,
            "qc": q.verdict,
            "reasons": q.reasons,
            "layout": r["layout"],
            "render_ms": r["render_ms"],
        }
    except (JobCancelledError, ffmpeg.FFmpegCancelledError):
        _set_status(short_id, ShortStatus.picked)
        shutil.rmtree(root / f"v{version_no}", ignore_errors=True)
        raise JobCancelledError from None
    except Exception:
        if job.is_last_attempt:
            _set_status(short_id, ShortStatus.failed)
        else:
            _set_status(short_id, ShortStatus.picked)
        shutil.rmtree(root / f"v{version_no}", ignore_errors=True)
        raise
