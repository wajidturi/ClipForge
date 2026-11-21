"""Build and run the FFmpeg graphs that turn a segment into a finished Short.

Pass 1 `edit`  : keep only the EDL spans (trim + concat), near-lossless intermediate.
Pass 2 `final` : layout (crop/stack/bubble/full) -> zoom -> captions/hook -> audio
                 chain -> H.264 (NVENC when it really works, else x264) + AAC.
The graph is written to a file (`-/filter_complex`), so long crop expressions never
hit command-line limits, and ffmpeg runs in the work folder so the subtitle file is
referenced by name.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from clipforge.core import ffmpeg
from clipforge.pipeline.render.edl import Edl
from clipforge.pipeline.render.effects import audio_chain, zoom_expression
from clipforge.pipeline.render.reframe import Box, x_expression

OUT_W, OUT_H = 1080, 1920
FPS = 30


@lru_cache
def video_encoder() -> tuple[str, ...]:
    """NVENC only if a real test encode succeeds (listing it is not enough: old
    drivers expose it and then fail). Otherwise x264."""
    try:
        r = subprocess.run(
            [
                ffmpeg._exe("ffmpeg"),
                "-v",
                "error",
                "-nostdin",
                "-f",
                "lavfi",
                "-i",
                "color=black:s=256x256:d=0.2",
                "-c:v",
                "h264_nvenc",
                "-f",
                "null",
                "-",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if r.returncode == 0:
            return ("-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0")
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ("-c:v", "libx264", "-preset", "medium", "-crf", "20")


def edit_pass(
    segment: Path,
    segment_start: float,
    edl: Edl,
    out: Path,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    """Cut the segment down to the EDL spans (times relative to the segment file)."""
    parts, labels = [], []
    for i, sp in enumerate(edl.spans):
        a, b = max(0.0, sp.start - segment_start), max(0.0, sp.end - segment_start)
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    graph = ";".join(parts) + f";{''.join(labels)}concat=n={len(edl.spans)}:v=1:a=1[v][a]"
    gfile = out.with_suffix(".edit.txt")
    gfile.write_text(graph, encoding="utf-8")
    ffmpeg.run_ffmpeg(
        [
            "-i",
            str(segment),
            "-/filter_complex",
            str(gfile),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "12",
            "-c:a",
            "pcm_s16le",
            str(out),
        ],
        duration_s=edl.duration,
        is_cancelled=is_cancelled,
    )


@dataclass
class Plan:
    layout: str  # crop | stack | bubble | full
    src_w: int
    src_h: int
    duration: float
    crop_keys: list[tuple[float, float]] = field(default_factory=lambda: [(0.0, 0.5)])
    cam: Box | None = None
    zoom_peaks: list[float] = field(default_factory=list)
    out_w: int = OUT_W
    out_h: int = OUT_H

    @property
    def top_h(self) -> int:
        """Stack layout: height of the facecam band."""
        if not self.cam:
            return 0
        cam_ar = (self.cam.w * self.src_w) / max(1.0, self.cam.h * self.src_h)
        return _even(min(max(self.out_w / cam_ar, self.out_h * 0.28), self.out_h * 0.42))


def _even(v: float) -> int:
    return max(2, int(v) // 2 * 2)


def _window(plan: Plan, out_ar: float) -> tuple[int, int, float]:
    """(crop w, crop h, scale for keyframes) for a window of aspect `out_ar` (w/h)."""
    ch = plan.src_h
    cw = _even(ch * out_ar)
    if cw > plan.src_w:  # source narrower than the target: use full width
        cw = _even(plan.src_w)
        ch = _even(cw / out_ar)
    return cw, ch, float(plan.src_w)


def video_graph(plan: Plan, ass_name: str | None) -> str:
    ow, oh = plan.out_w, plan.out_h
    g: list[str] = []
    if plan.layout == "full":
        g.append("[0:v]split[a][b]")
        g.append(
            f"[a]scale={ow}:{oh}:force_original_aspect_ratio=increase,crop={ow}:{oh},"
            "boxblur=24:2,eq=brightness=-0.12[bg]"
        )
        g.append(f"[b]scale={ow}:-2[fg]")
        g.append("[bg][fg]overlay=(W-w)/2:(H-h)/2[base]")
    elif plan.layout == "stack" and plan.cam:
        top = plan.top_h
        cw, ch, scale = _window(plan, ow / (oh - top))
        c = plan.cam
        g.append("[0:v]split[a][b]")
        g.append(
            f"[a]crop={_even(c.w * plan.src_w)}:{_even(c.h * plan.src_h)}:"
            f"{int(c.x * plan.src_w)}:{int(c.y * plan.src_h)},scale={ow}:{top},setsar=1[top]"
        )
        g.append(
            f"[b]crop={cw}:{ch}:'{x_expression(plan.crop_keys, scale)}':{(plan.src_h - ch) // 2},"
            f"scale={ow}:{oh - top},setsar=1[bot]"
        )
        g.append("[top][bot]vstack[base]")
    elif plan.layout == "bubble" and plan.cam:
        cw, ch, scale = _window(plan, ow / oh)
        c = plan.cam
        side = _even(max(c.w * plan.src_w, c.h * plan.src_h))
        cx = int(min(max(c.cx * plan.src_w - side / 2, 0), plan.src_w - side))
        cy = int(min(max(c.cy * plan.src_h - side / 2, 0), plan.src_h - side))
        d = 440
        g.append("[0:v]split[a][b]")
        g.append(
            f"[a]crop={cw}:{ch}:'{x_expression(plan.crop_keys, scale)}':{(plan.src_h - ch) // 2},"
            f"scale={ow}:{oh},setsar=1[game]"
        )
        circle = f"if(lte(hypot(X-{d // 2},Y-{d // 2}),{d // 2 - 2}),255,0)"  # round mask
        g.append(
            f"[b]crop={side}:{side}:{cx}:{cy},scale={d}:{d},format=yuva420p,"
            f"geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':a='{circle}'[cam]"
        )
        g.append("[game][cam]overlay=(W-w)/2:140[base]")
    else:  # crop
        cw, ch, scale = _window(plan, ow / oh)
        g.append(
            f"[0:v]crop={cw}:{ch}:'{x_expression(plan.crop_keys, scale)}':{(plan.src_h - ch) // 2},"
            f"scale={ow}:{oh},setsar=1[base]"
        )
    z = zoom_expression(plan.zoom_peaks)
    tail = "[base]"
    if z != "1":
        g.append(
            f"[base]scale=w='2*trunc({ow // 2}*({z}))':h='2*trunc({oh // 2}*({z}))':eval=frame,"
            f"crop={ow}:{oh}[zoomed]"
        )
        tail = "[zoomed]"
    subs = f",subtitles=filename={ass_name}" if ass_name else ""
    g.append(f"{tail}fps={FPS}{subs},format=yuv420p[v]")
    return ";\n".join(g)


def final_pass(
    edited: Path,
    plan: Plan,
    out: Path,
    *,
    ass: Path | None,
    measured: dict[str, str] | None,
    on_progress: Callable[[float], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    workdir = out.parent
    if ass is not None and ass.parent != workdir:
        raise ValueError("captions file must sit next to the output")
    graph = video_graph(plan, ass.name if ass else None) + f";\n[0:a]{audio_chain(measured)}[a]"
    gfile = workdir / f"{out.stem}.graph.txt"
    gfile.write_text(graph, encoding="utf-8")
    ffmpeg.run_ffmpeg(
        [
            "-i",
            str(edited),
            "-/filter_complex",
            gfile.name,
            "-map",
            "[v]",
            "-map",
            "[a]",
            *video_encoder(),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            out.name,
        ],
        duration_s=plan.duration,
        on_progress=on_progress,
        is_cancelled=is_cancelled,
        cwd=workdir,
    )


def extract_frame(video: Path, t: float, out: Path) -> Path:
    subprocess.run(
        [
            ffmpeg._exe("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            f"{max(0.0, t):.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(out),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        timeout=60,
    )
    return out
