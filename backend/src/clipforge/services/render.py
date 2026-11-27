"""The `short.render` job: one pick -> one new ShortVersion (MP4, cover, QC).

Two stages: the *cut* (segment, pause removal, face/facecam analysis, loudness,
editor preview; cached, see services/cuts.py) and the *compose* stage that draws
the scene (template, captions, effects, stickers, logo) on top of it. A studio
re-render with a new look only runs the compose stage.

A QC FAIL triggers one automatic re-cut (a sentence later at the start, or one more
sentence at the end) before giving up. Versions never overwrite each other, and the
source footage is never modified.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
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
    EditRequest,
    MediaAsset,
    QcReport,
    Segment,
    Short,
    ShortPart,
    ShortVersion,
    Signal,
    Source,
    Transcript,
)
from clipforge.db.session import get_sessionmaker
from clipforge.jobs.registry import JobCancelledError, JobContext, PermanentJobError
from clipforge.pipeline.render import captions, compose, cover, qc, reframe, scene_render
from clipforge.pipeline.render import scene as sc
from clipforge.pipeline.render.edl import apply_fixes, build_edl
from clipforge.pipeline.transcription.sentences import Word
from clipforge.services import brand_assets, cuts, settings_store

log = get_logger(__name__)

ASPECTS = {"4:5": (1080, 1350, AssetKind.aspect_4x5), "1:1": (1080, 1080, AssetKind.aspect_1x1)}


def defaults() -> dict[str, Any]:
    """Render options used when a request leaves them out (Settings -> Rendering)."""
    s = settings_store.effective()
    style = s.render_style if s.render_style in captions.STYLES else "template"
    return {"style": style, "template": s.render_template, "aspects": list(s.render_aspects)}


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
        prev = s.get(ShortVersion, short.active_version_id) if short.active_version_id else None
        src = s.get(Source, short.source_id)
        return {
            "short": {
                "id": short.id,
                "source_id": short.source_id,
                "hook": short.hook,
                "title": short.title,
                "channel": short.credit or (src.channel_name if src else None),
                "keywords": list(short.keywords or []),
            },
            "had_render": prev is not None,
            "prev_scene": (prev.settings or {}).get("scene") if prev else None,
            "start": part.start_s,
            "end": part.end_s,
            "loud": list(loud),
            "hottest": hottest,
            "sentences": sentences,
            "next_no": next_no,
            "words": [Word(*w) for w in data["words"]],
            "caption_overrides": dict(prev.caption_overrides or {}) if prev else {},
        }


def word_key(start: float) -> str:
    """Stable id of a transcript word: its start time in the source, 2 decimals."""
    return f"{start:.2f}"


def apply_caption_overrides(words: list[Word], overrides: dict[str, str]) -> list[Word]:
    """Studio caption fixes: replace a word's text, or hide it with an empty string.

    Only the captions change; the audio cut (EDL) still uses the original words.
    """
    if not overrides:
        return words
    out: list[Word] = []
    for w in words:
        new = overrides.get(word_key(w.start))
        if new is None:
            out.append(w)
        elif new.strip():
            out.append(Word(w.start, w.end, " " + new.strip(), w.prob))
    return out


def restore_after_stop(short_id: uuid.UUID) -> None:
    """After a stop: a Short left 'rendering' goes back to review (it has a video) or
    picked (it has none)."""
    with get_sessionmaker()() as s:
        short = s.get(Short, short_id)
        if short is not None and short.status == ShortStatus.rendering:
            short.status = ShortStatus.review if short.active_version_id else ShortStatus.picked
            s.commit()


def _set_status(short_id: uuid.UUID, status: ShortStatus, **extra: Any) -> None:
    with get_sessionmaker()() as s:
        short = s.get(Short, short_id)
        if short is not None:
            short.status = status
            for k, v in extra.items():
                setattr(short, k, v)
            s.commit()


# ------------------------------------------------------------------ scene
def placeholder_values(info: dict[str, Any], cut: cuts.Cut) -> dict[str, str | None]:
    sh = info["short"]
    return {
        "hook": sh["hook"],
        "title": sh["title"],
        "channel": sh["channel"] or "",
        "reaction": cut.data.get("reaction") or "NO WAY!",
    }


def resolve_scene(
    opts: dict[str, Any], info: dict[str, Any], cut: cuts.Cut
) -> tuple[sc.Scene, str | None]:
    """Which scene to draw: one sent by the studio, the previous version's (kept on a
    plain re-render), or the template's defaults. Returns (scene, note)."""
    d = cut.data
    ctx = sc.Ctx(
        d["duration"], d["zoom_peaks"], has_cam=cuts.has_people(d), cam_kind=cuts.cam_boxes(d)[2]
    )
    prev = sc.Scene.model_validate(info["prev_scene"]) if info.get("prev_scene") else None
    if opts.get("scene"):
        scene = sc.Scene.model_validate(opts["scene"])
    else:
        requested = opts.get("template") or opts.get("layout") or "auto"
        requested = sc.LEGACY_LAYOUT.get(requested, requested)
        if prev is not None and requested in ("auto", prev.template):
            scene = prev
        else:
            t, _ = sc.resolve_template(requested, ctx.has_cam, ctx.cam_kind)
            scene = sc.switch_template(prev, t, ctx) if prev else sc.default_scene(t, ctx)
        style = opts.get("style")
        if style and style != "template" and style in captions.STYLES:
            scene.captions = sc.caption_preset(style, y=scene.captions.y)
        if opts.get("canvas"):  # a size chosen on Create / the render request
            scene.canvas = sc.Canvas.model_validate(opts["canvas"])
    used, note = sc.resolve_template(scene.template, ctx.has_cam, ctx.cam_kind)
    if used != scene.template:
        scene = sc.switch_template(scene, used, ctx)
    return scene, note


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
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()

    cut = cuts.ensure_cut(job, info, start, end)
    plan = cut.plan
    job.check_cancelled()
    scene, note = resolve_scene(opts, info, cut)
    values = placeholder_values(info, cut)
    words = apply_fixes(cut.keyed(), opts.get("caption_overrides") or {})
    final = out_dir / "short.mp4"
    job.progress(42, "rendering")
    scene_render.render_scene(
        cut.edited,
        scene,
        plan,
        final,
        words=words,
        keywords=info["short"]["keywords"],
        values=values,
        image_path=brand_assets.image_path,
        on_progress=ctx.slice(42, 85, "rendering"),
        is_cancelled=lambda: job.cancelled,
    )

    job.progress(86, "making the cover")
    frame = compose.extract_frame(final, scene_render.peak_time(plan) + 0.3, out_dir / "frame.jpg")
    hook_shown = any(ly.role == "hook" and ly.visible for ly in scene.layers)
    cover_path = cover.make_cover(
        frame, None if hook_shown else info["short"]["hook"], out_dir / "cover.jpg"
    )
    frame.unlink(missing_ok=True)

    cap_settings = scene.captions.model_dump()
    extras: dict[str, Path] = {}
    for aspect in opts.get("aspects") or []:
        if aspect not in ASPECTS:
            continue
        w, h, _kind = ASPECTS[aspect]
        job.progress(88, f"rendering {aspect}")
        blur = scene.regions.fit == "blur" and scene.template in ("cinematic", "floating_facecam")
        eplan = compose.Plan(
            "full" if blur else "crop",
            plan.src_w,
            plan.src_h,
            plan.duration,
            reframe.track_targets(
                plan.targets, plan.cuts, min(1.0, plan.src_h * (w / h) / plan.src_w)
            ),
            None,
            plan.zoom_peaks if scene.effects.zoom_punch else [],
            w,
            h,
        )
        eass = out_dir / f"captions_{w}x{h}.ass"
        eass.write_text(
            captions.build_ass(
                words if scene.captions.visible else [],
                settings=cap_settings,
                keywords=info["short"]["keywords"],
                duration=plan.duration,
                size=(w, h),
            ),
            encoding="utf-8",
        )
        extras[aspect] = out_dir / f"short_{aspect.replace(':', 'x')}.mp4"
        compose.final_pass(
            cut.edited,
            eplan,
            extras[aspect],
            ass=eass,
            measured=plan.measured,
            is_cancelled=lambda: job.cancelled,
        )

    job.progress(94, "quality check")
    ass = out_dir / "captions.ass"
    coverage = (
        captions.coverage(words, ass.read_text("utf-8"))
        if scene.captions.visible and ass.exists()
        else 1.0
    )
    result = qc.check(final, caption_coverage=coverage, expected_s=plan.duration)
    for g in [*out_dir.glob("*.txt"), *out_dir.glob("*.png")]:
        g.unlink()
    return {
        "final": final,
        "cover": cover_path,
        "ass": ass if ass.exists() else None,
        "extras": extras,
        "qc": result,
        "edl": build_edl(info["words"], start, end),
        "layout": scene.template,
        "scene": scene.model_dump(),
        "note": note,
        "cut_key": cut.key,
        "cam": cut.data["cam"],
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
    root = get_settings().resolved_data_dir

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
                **{k: v for k, v in opts.items() if k not in ("caption_overrides", "scene")},
                "template": r["layout"],
                "style": r["scene"]["captions"]["preset"],
                "scene": r["scene"],
                "note": r["note"],
                "cut_key": r["cut_key"],
                "layout_used": r["layout"],
                "cam": r["cam"],
                "zoom_peaks": r["zoom_peaks"],
                "encoder": r["encoder"],
                "range": [start, end],
            },
            edl=r["edl"].to_json(),
            caption_overrides=opts.get("caption_overrides") or {},
            render_ms=r["render_ms"],
            status=VersionStatus.ready,
        )
        s.add(ver)
        s.flush()
        s.add_all(
            [
                asset(AssetKind.mp4, r["final"], ver.id),
                asset(AssetKind.cover, r["cover"], ver.id),
            ]
        )
        if r["ass"] is not None:
            s.add(asset(AssetKind.caption_ass, r["ass"], ver.id))
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
        if opts.get("edit_id"):  # an applied AI/manual edit points at its result
            er = s.get(EditRequest, uuid.UUID(str(opts["edit_id"])))
            if er is not None:
                er.result_version_id = ver.id
        s.commit()
        return ver.id


def render(job: JobContext, short_id: uuid.UUID, options: dict[str, Any]) -> dict[str, Any]:
    opts = {**defaults(), **{k: v for k, v in options.items() if v is not None}}
    if opts["style"] not in captions.STYLES and opts["style"] != "template":
        raise PermanentJobError(f"unknown caption style '{opts['style']}'")
    requested = opts.get("template") or opts.get("layout") or "auto"
    if requested not in (*sc.TEMPLATE_IDS, "auto", *sc.LEGACY_LAYOUT):
        raise PermanentJobError(f"unknown template '{requested}'")
    if opts.get("scene"):
        try:
            sc.Scene.model_validate(opts["scene"])
        except ValueError as e:
            raise PermanentJobError(f"invalid scene: {e}") from None
    if opts.get("canvas"):
        try:
            sc.Canvas.model_validate(opts["canvas"])
        except ValueError as e:
            raise PermanentJobError(f"invalid video size: {e}") from None
    info = _load(short_id)
    back = ShortStatus.review if info["had_render"] else ShortStatus.picked
    if "caption_overrides" not in opts:  # keep earlier caption fixes on a re-render
        opts["caption_overrides"] = info["caption_overrides"]
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
            opts["scene"] = r["scene"]  # same look on the re-cut
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
            "template": r["layout"],
            "note": r["note"],
            "render_ms": r["render_ms"],
        }
    except (JobCancelledError, ffmpeg.FFmpegCancelledError):
        _set_status(short_id, back)
        shutil.rmtree(root / f"v{version_no}", ignore_errors=True)
        raise JobCancelledError from None
    except Exception:
        _set_status(
            short_id, ShortStatus.failed if job.is_last_attempt and not info["had_render"] else back
        )
        shutil.rmtree(root / f"v{version_no}", ignore_errors=True)
        raise
