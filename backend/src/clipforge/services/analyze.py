"""The `source.analyze` job: transcript + signals + HEAT for one source.

Steps (each reports into one progress bar; only transcription is mandatory):
  1. transcribe (cached by audio hash)      5-60 %
  2. loudness + text cues                    60-66 %
  3. chat replay (YouTube / Twitch links)    66-72 %
  4. viewer clips (Twitch + app credentials) 72-75 %
  5. most-replayed heat map (YouTube)        75 %
  6. picture: proxy, motion, faces, cuts     75-95 %   (setting vision_enabled)
     + on-screen banners via OCR                       (setting banner_ocr)
  7. HEAT per sentence                       95-100 %
Optional steps that fail are recorded as warnings; the source still becomes ready.
All stored times are full-video seconds (audio time + window start).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from clipforge.core import ffmpeg
from clipforge.core.config import Settings
from clipforge.core.logging import get_logger
from clipforge.db.enums import AssetKind, AssetOwner, Platform, SignalType, SourceStatus
from clipforge.db.models import MediaAsset, Segment, Signal, Source, Transcript
from clipforge.db.session import get_sessionmaker
from clipforge.jobs.registry import JobCancelledError, JobContext, PermanentJobError
from clipforge.pipeline.ingest.timewin import Window
from clipforge.pipeline.signals import Spike, text_cues
from clipforge.pipeline.signals import audio as audio_sig
from clipforge.pipeline.signals import banners as banner_sig
from clipforge.pipeline.signals import chat as chat_sig
from clipforge.pipeline.signals import clips as clip_sig
from clipforge.pipeline.signals import heat as heat_sig
from clipforge.pipeline.signals import replay as replay_sig
from clipforge.pipeline.signals import vision as vision_sig
from clipforge.pipeline.transcription.sentences import Sentence, Word, build_sentences
from clipforge.pipeline.transcription.whisper import Transcriber, TranscriptionCancelledError
from clipforge.services import ingest, settings_store
from clipforge.services.sources import original_file, source_dir

log = get_logger(__name__)

CURVE_HOP_S = 2.0  # stored curve resolution; the timeline API downsamples further


def make_transcriber(settings: Settings) -> Transcriber:
    """Factory (patched in tests)."""
    return Transcriber(
        model=settings.whisper_model,
        device=settings.whisper_device,
        download_root=settings.resolved_data_dir / "models" / "whisper",
    )


class _Run:
    def __init__(self, ctx: JobContext, source_id: uuid.UUID, settings: Settings) -> None:
        self.ctx, self.id, self.settings = ctx, source_id, settings
        self.dir = source_dir(settings, source_id)
        self.warnings: list[str] = []
        self.spikes: list[Spike] = []
        self.available: set[str] = set()
        self.curves: dict[str, Any] = {"hop_s": CURVE_HOP_S}
        self.steps: dict[str, str] = {}

    # ----------------------------------------------------------------- helpers
    def slice(self, lo: float, hi: float) -> Callable[[float, str | None], None]:
        def report(pct: float, step: str | None = None) -> None:
            self.ctx.progress(lo + (hi - lo) * max(0.0, min(100.0, pct)) / 100, step)

        return report

    def cancelled(self) -> bool:
        return self.ctx.cancelled

    def optional(self, name: str, fn: Callable[[], None]) -> None:
        """Run an optional step; failures become warnings instead of failing the job."""
        self.ctx.check_cancelled()
        try:
            fn()
            self.steps.setdefault(name, "done")
        except (JobCancelledError, InterruptedError, ffmpeg.FFmpegCancelledError):
            raise JobCancelledError from None
        except Exception as e:
            if self.ctx.cancelled:
                raise JobCancelledError from None
            log.warning("analyze.step_failed", step=name, error=str(e))
            self.steps[name] = "failed"
            self.warnings.append(f"{name}: {str(e)[:200]}")

    def load(self) -> tuple[Source, MediaAsset, MediaAsset | None]:
        with get_sessionmaker()() as s:
            src = s.get(Source, self.id)
            if src is None:
                raise PermanentJobError("source was deleted")
            assets = s.scalars(
                select(MediaAsset).where(
                    MediaAsset.owner_type == AssetOwner.source, MediaAsset.owner_id == self.id
                )
            ).all()
            audio = next((a for a in assets if a.kind == AssetKind.audio), None)
            video = next((a for a in assets if a.kind == AssetKind.video), None)
            if audio is None:
                raise PermanentJobError("no audio for this source yet; add it again")
            for o in (src, audio, *([video] if video else [])):
                s.expunge(o)
            return src, audio, video

    # ----------------------------------------------------------------- steps
    def transcribe(self, src: Source, audio: MediaAsset, offset: float) -> list[Word]:
        words_file = self.dir / "words.json"
        if words_file.exists():
            cached = json.loads(words_file.read_text(encoding="utf-8"))
            if cached.get("audio_sha256") == audio.sha256 and cached.get("offset_s") == offset:
                self.ctx.progress(60, "transcript already up to date")
                self.steps["transcribe"] = "cached"
                return [Word(*w) for w in cached["words"]]
        t = make_transcriber(self.settings)
        res = t.transcribe(
            self.settings.resolved_data_dir / audio.path,
            language=self.settings.transcribe_language,
            progress=self.slice(5, 60),
            is_cancelled=self.cancelled,
        )
        self.warnings += res.notes
        words = [
            Word(round(w.start + offset, 3), round(w.end + offset, 3), w.text, round(w.prob, 3))
            for w in res.words
        ]
        words_file.write_text(
            json.dumps(
                {
                    "audio_sha256": audio.sha256,
                    "offset_s": offset,
                    "model": res.model,
                    "device": res.device,
                    "language": res.language,
                    "language_prob": res.language_prob,
                    "words": [[w.start, w.end, w.text, w.prob] for w in words],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with get_sessionmaker()() as s:
            s.execute(delete(Transcript).where(Transcript.source_id == self.id))
            s.add(
                Transcript(
                    source_id=self.id,
                    model=res.model,
                    device=res.device,
                    language=res.language,
                    language_prob=res.language_prob,
                    words_path=words_file.relative_to(self.settings.resolved_data_dir).as_posix(),
                    word_count=len(words),
                )
            )
            src_row = s.get(Source, self.id)
            if src_row is not None and res.language:
                src_row.language = res.language
            s.commit()
        self.steps["transcribe"] = f"done ({res.device}, {res.model})"
        return words

    def audio_signals(self, audio: MediaAsset, offset: float) -> None:
        x = audio_sig.decode_pcm(self.settings.resolved_data_dir / audio.path)
        db = audio_sig.loudness_db(x, hop_s=0.5)
        self.spikes += audio_sig.loud_spikes(
            db, hop_s=0.5, offset_s=offset, min_rise_db=self.settings.loud_rise_db
        )
        self.available.add("loud")
        step = int(CURVE_HOP_S / 0.5)
        self.curves["loud"] = audio_sig.curve(db, 0.5, offset, max(1, len(db) // step))
        self.curves["loud_offset_s"] = offset

    def chat(self, src: Source, window: Window) -> None:
        if src.platform not in (Platform.youtube, Platform.twitch):
            self.steps["chat"] = "not available for this site"
            return
        path = ingest.make_downloader(self.settings).fetch_chat(src.url, self.dir)
        if path is None:
            self.steps["chat"] = "no chat replay"
            return
        msgs = chat_sig.parse_chat_file(path)
        spikes, rate = chat_sig.chat_spikes(
            msgs,
            window.start_s,
            window.end_s or (src.duration_s or 0),
            ratio=self.settings.chat_spike_ratio,
            min_per_min=self.settings.chat_spike_min_per_min,
        )
        self.spikes += spikes
        self.available.add("chat_spike")
        self.curves["chat"] = [float(v) for v in rate]
        self.curves["chat_bin_s"] = 10.0
        self.curves["chat_offset_s"] = window.start_s
        self.steps["chat"] = f"{len(msgs)} messages, {len(spikes)} spikes"

    def clips(self, src: Source, window: Window) -> None:
        if src.platform != Platform.twitch or not src.external_id.startswith("v"):
            self.steps["clips"] = "only for Twitch VODs"
            return
        if not (self.settings.twitch_client_id and self.settings.twitch_client_secret):
            self.steps["clips"] = "add Twitch app credentials in Settings to use viewer clips"
            return
        clips = clip_sig.vod_clips(
            src.external_id,
            self.settings.twitch_client_id,
            self.settings.twitch_client_secret.get_secret_value(),
        )
        self.spikes += clip_sig.clip_spikes(clips, window.start_s, window.end_s or 1e12)
        self.available.add("clip")
        self.steps["clips"] = f"{len(clips)} clips"

    def replay(self, src: Source, window: Window) -> None:
        heat = (src.meta or {}).get("heatmap") or []
        if not heat:
            self.steps["replay"] = "not available for this video"
            return
        self.spikes += replay_sig.replay_spikes(heat, window.start_s, window.end_s or 1e12)
        self.available.add("replay")
        self.curves["replay"] = replay_sig.replay_curve(heat)

    def proxy(self, src: Source, video: MediaAsset | None, window: Window) -> Path:
        dst = self.dir / "proxy_360p.mp4"
        if dst.exists() and dst.stat().st_size > 0:
            return dst
        prog = self.slice(75, 80)
        if src.platform == Platform.file:
            original = original_file(self.settings, src)
            if original is None or video is None:
                raise RuntimeError("this source has no video track")
            start, end = window.start_s, window.end_s
            inp = original
        else:
            prog(0, "downloading a small copy of the video")
            inp = ingest.make_downloader(self.settings).download_proxy(
                src.url,
                self.dir,
                window if (window.start_s or window.end_s) else None,
                is_cancelled=self.cancelled,
            )
            start, end = 0.0, None  # the download already starts at the window
        args = ["-ss", f"{start:.3f}"] if start else []
        args += ["-i", str(inp)]
        if end is not None:
            args += ["-t", f"{end - start:.3f}"]
        args += [
            "-an",
            "-vf",
            f"scale=-2:{vision_sig.PROXY_HEIGHT},fps={vision_sig.PROXY_FPS}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "30",
            str(dst),
        ]
        prog(50, "preparing frames")
        ffmpeg.run_ffmpeg(
            args, duration_s=(end - start) if end else src.duration_s, is_cancelled=self.cancelled
        )
        if inp != original_file(self.settings, src):
            inp.unlink(missing_ok=True)
        with get_sessionmaker()() as s:
            ingest._add_asset(s, self.id, AssetKind.proxy, dst)
            s.commit()
        return dst

    def vision(self, src: Source, video: MediaAsset | None, window: Window) -> None:
        if src.platform == Platform.file and video is None:
            self.steps["vision"] = "audio-only source"
            return
        proxy = self.proxy(src, video, window)
        try:
            face_model: Path | None = vision_sig.ensure_face_model(
                self.settings.resolved_data_dir / "models"
            )
        except Exception as e:
            face_model = None
            self.warnings.append(f"faces: model download failed ({str(e)[:120]}); motion only")
        report = self.slice(80, 92)
        stats = vision_sig.analyze_frames(
            proxy,
            window.start_s,
            face_model=face_model,
            progress=lambda p: report(p, "looking at the picture"),
            is_cancelled=self.cancelled,
        )
        self.spikes += vision_sig.moment_spikes(stats)
        self.spikes += vision_sig.cut_spikes(proxy, window.start_s)
        self.curves["motion"] = stats.motion
        self.curves["motion_offset_s"] = window.start_s
        if self.settings.banner_ocr:
            report_b = self.slice(92, 95)
            self.spikes += banner_sig.banner_spikes(
                proxy,
                window.start_s,
                self.settings.banner_words or None,
                progress=lambda p: report_b(p, "reading on-screen text"),
                is_cancelled=self.cancelled,
            )
            self.available.add("banner")
        self.steps["vision"] = "done" + (" (faces)" if face_model else " (motion only)")

    def save(self, sentences: list[Sentence]) -> None:
        self.available |= {"moment", "laugh"}
        scored = heat_sig.score_ranges(
            [(s.start, s.end) for s in sentences], self.spikes, self.available
        )
        (self.dir / "curves.json").write_text(json.dumps(self.curves), encoding="utf-8")
        with get_sessionmaker()() as s:
            tr = s.scalar(select(Transcript).where(Transcript.source_id == self.id))
            assert tr is not None
            s.execute(delete(Segment).where(Segment.transcript_id == tr.id))
            s.add_all(
                Segment(
                    transcript_id=tr.id,
                    idx=i,
                    start_s=se.start,
                    end_s=se.end,
                    text=se.text,
                    heat=sc.heat,
                    tags=sc.tags,
                )
                for i, (se, sc) in enumerate(zip(sentences, scored, strict=True))
            )
            s.execute(delete(Signal).where(Signal.source_id == self.id))
            s.add_all(
                Signal(
                    source_id=self.id,
                    type=SignalType(sp.type),
                    start_s=sp.start,
                    end_s=sp.end,
                    score=sp.score,
                    label=sp.label,
                    meta=sp.meta,
                )
                for sp in self.spikes
            )
            src = s.get(Source, self.id)
            assert src is not None
            src.status = SourceStatus.ready
            src.error = src.error_hint = None
            src.meta = {
                **(src.meta or {}),
                "analysis": {
                    "steps": self.steps,
                    "warnings": self.warnings,
                    "available": sorted(self.available),
                    "sentences": len(sentences),
                    "signals": len(self.spikes),
                },
            }
            s.commit()


def analyze(ctx: JobContext, source_id: uuid.UUID, options: dict[str, Any]) -> dict[str, Any]:
    settings = settings_store.effective()
    if "vision" in options:
        settings = settings.model_copy(update={"vision_enabled": bool(options["vision"])})
    if "banners" in options:
        settings = settings.model_copy(update={"banner_ocr": bool(options["banners"])})
    run = _Run(ctx, source_id, settings)
    if options.get("force_transcribe"):
        (run.dir / "words.json").unlink(missing_ok=True)
    try:
        src, audio, video = run.load()
        ingest._update(source_id, status=SourceStatus.analyzing, error=None, error_hint=None)
        window = Window(src.window_start_s or 0.0, src.window_end_s or src.duration_s)
        offset = window.start_s

        try:
            words = run.transcribe(src, audio, offset)
        except TranscriptionCancelledError:
            raise JobCancelledError from None
        sentences = build_sentences(words)
        ctx.progress(61, "measuring loudness")
        run.optional("loudness", lambda: run.audio_signals(audio, offset))
        run.spikes += text_cues.text_spikes(sentences)
        ctx.progress(66, "reading chat replay")
        run.optional("chat", lambda: run.chat(src, window))
        ctx.progress(72, "checking viewer clips")
        run.optional("clips", lambda: run.clips(src, window))
        run.optional("replay", lambda: run.replay(src, window))
        if settings.vision_enabled:
            run.optional("vision", lambda: run.vision(src, video, window))
        else:
            run.steps["vision"] = "off"
        ctx.progress(96, "scoring moments")
        run.save(sentences)
    except JobCancelledError:
        ingest._update(source_id, status=SourceStatus.failed, error="Analysis cancelled")
        raise
    except PermanentJobError as e:
        ingest._update(source_id, status=SourceStatus.failed, error=str(e))
        raise
    except Exception as e:
        msg = f"Analysis failed: {str(e)[:300]}"
        if ctx.is_last_attempt:
            ingest._update(source_id, status=SourceStatus.failed, error=msg)
        else:  # a retry is queued; show why while it waits
            ingest._update(source_id, error=msg, error_hint="Retrying automatically…")
        raise
    result = {
        "sentences": len(sentences),
        "signals": len(run.spikes),
        "warnings": run.warnings,
        "steps": run.steps,
    }
    log.info(
        "source.analyzed",
        source_id=str(source_id),
        **{k: v for k, v in result.items() if k != "steps"},
    )
    return result


# ---------------------------------------------------------------- read models
def load_curves(settings: Settings, source_id: uuid.UUID) -> dict[str, Any]:
    p = source_dir(settings, source_id) / "curves.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def spike_dict(sp: Spike) -> dict[str, Any]:
    return asdict(sp)
