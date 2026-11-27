"""Person cut-out (matte) for the facecam panel: lets a template swap the streamer's
background (soft blur, gradients ...) without a green screen.

One grayscale video the size of the whole frame (scaled to MATTE_W wide) is made per
cut: white where a person is, black elsewhere, only inside the facecam regions. The
renderer crops it like the facecam and uses it as alpha; the studio preview loads the
same video, so both cut the streamer out identically. Made once per cut: changing the
background later costs nothing.

Segmentation: MediaPipe's multiclass selfie model (background / hair / body skin /
face skin / clothes / accessories) on each region SEG_FPS times a second, smoothed over time so
the edge does not flicker, with blended frames in between, written at 30 fps.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from clipforge.core import ffmpeg
from clipforge.pipeline.render.reframe import Box

MATTE_W = 1280
SEG_FPS = 8  # masks per second (the model takes ~0.1 s on a CPU) ...
BLEND = 3  # ... with 3 blended frames per mask: written at 24 fps, then 30 fps
REGION_GROW = 1.5  # around a cam box: room for any tile crop of it
OUT_FPS = 30
SMOOTH = 0.7  # weight of the new mask (rest: previous frame)
EDGE_LO, EDGE_HI = 0.25, 0.75  # person probability mapped to 0..1 alpha (crisper edge)


class Segmenter(Protocol):
    def person(self, rgb: np.ndarray, ts_ms: int) -> np.ndarray:
        """Person probability (float32 0..1) for an RGB image, same height/width."""
        ...

    def close(self) -> None: ...


class MediaPipeSegmenter:
    def __init__(self, model: Path) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        self.seg = vision.ImageSegmenter.create_from_options(
            vision.ImageSegmenterOptions(
                base_options=BaseOptions(model_asset_path=str(model)),
                running_mode=vision.RunningMode.VIDEO,
                output_confidence_masks=True,
                output_category_mask=False,
            )
        )

    def person(self, rgb: np.ndarray, ts_ms: int) -> np.ndarray:
        import mediapipe as mp

        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = self.seg.segment_for_video(img, ts_ms)
        background: np.ndarray = np.asarray(res.confidence_masks[0].numpy_view())
        return np.clip(1.0 - background, 0.0, 1.0).astype(np.float32)

    def close(self) -> None:
        self.seg.close()


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    w: int
    h: int


def matte_size(src_w: int, src_h: int) -> tuple[int, int]:
    w = min(MATTE_W, src_w - src_w % 2)
    return w, max(2, round(src_h * w / src_w / 2) * 2)


def regions_for(cams: Sequence[Box], mw: int, mh: int) -> list[Region]:
    out = []
    for c in cams:
        b = c.expand(REGION_GROW, REGION_GROW)
        x, y = int(b.x * mw), int(b.y * mh)
        w, h = max(8, min(round(b.w * mw), mw - x)), max(8, min(round(b.h * mh), mh - y))
        out.append(Region(x, y, w, h))
    return out


def soft_edge(p: np.ndarray) -> np.ndarray:
    return np.clip((p - EDGE_LO) / (EDGE_HI - EDGE_LO), 0.0, 1.0)


def build_matte(
    video: Path,
    cams: Sequence[Box],
    out: Path,
    *,
    src_w: int,
    src_h: int,
    duration: float,
    make_segmenter: Callable[[], Segmenter],
    is_cancelled: Callable[[], bool] = lambda: False,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[int, int]:
    """Write the matte video to `out`; returns its (width, height)."""
    import cv2

    mw, mh = matte_size(src_w, src_h)
    regions = regions_for(cams, mw, mh)
    segs = [make_segmenter() for _ in regions]  # VIDEO mode keeps state per region
    exe = ffmpeg._exe("ffmpeg")
    reader = subprocess.Popen(
        [exe, "-hide_banner", "-loglevel", "error", "-i", str(video), "-an",
         "-vf", f"fps={SEG_FPS},scale={mw}:{mh}:flags=area",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    writer = subprocess.Popen(
        [exe, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{mw}x{mh}",
         "-r", str(SEG_FPS * BLEND), "-i", "-",
         "-vf", f"fps={OUT_FPS}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )  # fmt: skip
    err: list[bytes] = []
    drain = threading.Thread(target=lambda: err.append(writer.stderr.read()), daemon=True)  # type: ignore[union-attr]
    drain.start()
    prev: list[np.ndarray | None] = [None] * len(regions)
    last_canvas: np.ndarray | None = None
    size = mw * mh * 3
    n_frames = max(1, round(duration * SEG_FPS))
    i = 0
    try:
        assert reader.stdout is not None and writer.stdin is not None
        while True:
            buf = reader.stdout.read(size)
            if len(buf) < size:
                break
            if is_cancelled():
                raise ffmpeg.FFmpegCancelledError("cancelled")
            frame = np.frombuffer(buf, np.uint8).reshape(mh, mw, 3)
            canvas = np.zeros((mh, mw), np.float32)
            for k, r in enumerate(regions):
                crop = frame[r.y : r.y + r.h, r.x : r.x + r.w]
                p = segs[k].person(crop, int(i * 1000 / SEG_FPS))
                if p.shape != (r.h, r.w):
                    p = cv2.resize(p, (r.w, r.h), interpolation=cv2.INTER_LINEAR)
                last = prev[k]
                p = p if last is None else SMOOTH * p + (1 - SMOOTH) * last
                prev[k] = p
                view = canvas[r.y : r.y + r.h, r.x : r.x + r.w]
                np.maximum(view, soft_edge(p), out=view)
            if last_canvas is not None:  # the frames from the previous mask to this one
                for j in range(BLEND):
                    mix = last_canvas + (canvas - last_canvas) * (j / BLEND)
                    writer.stdin.write((mix * 255).astype(np.uint8).tobytes())
            last_canvas = canvas
            i += 1
            if on_progress:
                on_progress(min(99.0, i / n_frames * 100))
        if last_canvas is not None:  # the last mask holds to the end
            writer.stdin.write((last_canvas * 255).astype(np.uint8).tobytes() * BLEND)
        writer.stdin.close()
        writer.wait()
    except BaseException:
        for proc in (reader, writer):
            proc.kill()
        raise
    finally:
        reader.kill()
        reader.wait()
        drain.join(timeout=5)
        for s in segs:
            s.close()
    if writer.returncode != 0 or i == 0:
        detail = b"".join(err).decode(errors="replace")[-300:]
        raise ffmpeg.FFmpegError(f"matte encoding failed: {detail or 'no frames'}")
    return mw, mh


def matte_crop(
    rect: tuple[int, int, int, int], src_w: int, src_h: int, mw: int, mh: int
) -> tuple[int, int, int, int]:
    """A source-pixel crop (x, y, w, h) in matte pixels (even sizes, inside the frame)."""
    x, y, w, h = rect
    fx, fy = mw / src_w, mh / src_h
    cw = max(2, int(w * fx) // 2 * 2)
    ch = max(2, int(h * fy) // 2 * 2)
    cx = min(max(0, int(x * fx)), mw - cw)
    cy = min(max(0, int(y * fy)), mh - ch)
    return cx, cy, cw, ch
