"""Reframe 16:9 -> 9:16: find who/what to show, pick a layout, plan the crop path.

Layouts
- crop   : a 9:16 window that follows the main face (or the action when no face)
- stack  : streamer facecam on top, gameplay below (when a facecam box is found)
- bubble : gameplay fills the frame, round facecam at the top
- full   : whole frame fitted to the width over a blurred copy (groups, calls, wide shots)

All analysis runs on the edited clip, so times are output seconds. Boxes are
normalised (0..1 of width/height).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import cv2
import numpy as np

LAYOUTS = ("auto", "crop", "stack", "bubble", "full")


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def area(self) -> float:
        return self.w * self.h

    def expand(self, fx: float, fy: float) -> Box:
        w, h = min(1.0, self.w * fx), min(1.0, self.h * fy)
        x = min(max(0.0, self.cx - w / 2), 1 - w)
        y = min(max(0.0, self.cy - h / 2), 1 - h)
        return Box(x, y, w, h)


GRID_W, GRID_H = 32, 18  # coarse motion grid (cells of 5x5 px on a 160x90 thumbnail)
MOTION_MIN = 160 * 90 * 2  # total change below this = nothing moving worth following


@dataclass
class Sample:
    t: float
    faces: list[Box] = field(default_factory=list)
    motion_x: float | None = None  # horizontal centre of motion (0..1), whole frame
    motion: np.ndarray | None = None  # GRID_H x GRID_W change per cell

    def motion_centre(self, exclude: Box | None = None) -> float | None:
        """Centre of motion, optionally ignoring a region (the facecam: a talking
        streamer moves constantly and would drag the game crop onto the cam)."""
        if self.motion is None or exclude is None:
            return self.motion_x
        g = self.motion.copy()
        x0, x1 = int(exclude.x * GRID_W), int(np.ceil((exclude.x + exclude.w) * GRID_W))
        y0, y1 = int(exclude.y * GRID_H), int(np.ceil((exclude.y + exclude.h) * GRID_H))
        g[y0:y1, x0:x1] = 0
        col = g.sum(axis=0)
        # Half the whole-frame threshold: once the cam is masked, the action is often
        # a small fast region (a car, a player) rather than full-frame change.
        if col.sum() <= MOTION_MIN * 0.5:
            return None
        return float(((col * (np.arange(GRID_W) + 0.5)).sum() / col.sum()) / GRID_W)


@dataclass
class Analysis:
    width: int
    height: int
    duration: float
    samples: list[Sample]
    cuts: list[float]


# ------------------------------------------------------------------ analysis
class _FaceFinder:
    def __init__(self, model: Path) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        self.lm = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(model)),
                running_mode=vision.RunningMode.VIDEO,
                num_faces=4,
                min_face_detection_confidence=0.5,
            )
        )

    def find(self, bgr: np.ndarray, ts_ms: int) -> list[Box]:
        import mediapipe as mp

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        res = self.lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts_ms)
        out = []
        for pts in res.face_landmarks:
            xs = [p.x for p in pts]
            ys = [p.y for p in pts]
            x0, x1 = max(0.0, min(xs)), min(1.0, max(xs))
            y0, y1 = max(0.0, min(ys)), min(1.0, max(ys))
            if x1 > x0 and y1 > y0:
                out.append(Box(x0, y0, x1 - x0, y1 - y0))
        return out

    def close(self) -> None:
        self.lm.close()


def analyze(video: Path, *, face_model: Path | None, fps: float = 4.0) -> Analysis:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video.name}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, round(src_fps / fps))
    finder = _FaceFinder(face_model) if face_model else None
    samples: list[Sample] = []
    prev: np.ndarray | None = None
    i = 0
    try:
        while True:
            ok = cap.grab()
            if not ok:
                break
            if i % step == 0:
                _, frame = cap.retrieve()
                t = i / src_fps
                small = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY).astype(
                    np.float32
                )
                mx, grid = None, None
                if prev is not None:
                    diff = np.abs(small - prev)
                    grid = diff.reshape(GRID_H, 5, GRID_W, 5).sum(axis=(1, 3))
                    col = diff.sum(axis=0)
                    if col.sum() > MOTION_MIN:  # enough change to locate
                        mx = float((col * np.arange(160)).sum() / col.sum() / 160)
                prev = small
                faces = finder.find(frame, int(t * 1000)) if finder else []
                samples.append(Sample(t, faces, mx, grid))
            i += 1
    finally:
        cap.release()
        if finder:
            finder.close()
    duration = n / src_fps if n else (samples[-1].t if samples else 0.0)
    return Analysis(w, h, duration, samples, detect_cuts(video))


def detect_cuts(video: Path) -> list[float]:
    from scenedetect import ContentDetector, detect

    try:
        scenes = detect(str(video), ContentDetector(threshold=27.0, min_scene_len=8))
    except Exception:
        return []
    return [float(s.get_seconds()) for s, _ in scenes[1:]]


# ------------------------------------------------------------------ decisions
def detect_cam(samples: list[Sample]) -> Box | None:
    """A facecam: a small face that stays in one place, off the centre, most of the time."""
    small = [min(s.faces, key=lambda b: b.area) for s in samples if s.faces]
    if len(samples) < 4 or len(small) < 0.6 * len(samples):
        return None
    cx = np.array([b.cx for b in small])
    cy = np.array([b.cy for b in small])
    area = np.array([b.area for b in small])
    steady = cx.std() < 0.03 and cy.std() < 0.03
    tiny = float(np.median(area)) < 0.06
    off_centre = abs(float(np.median(cx)) - 0.5) > 0.18 or abs(float(np.median(cy)) - 0.5) > 0.18
    if not (steady and tiny and off_centre):
        return None
    med = Box(
        float(np.median([b.x for b in small])),
        float(np.median([b.y for b in small])),
        float(np.median([b.w for b in small])),
        float(np.median([b.h for b in small])),
    )
    return med.expand(2.6, 2.2)  # head + shoulders, roughly the cam overlay


def choose_layout(a: Analysis, cam: Box | None, requested: str = "auto") -> str:
    if requested in ("stack", "bubble") and cam is None:
        return "crop"  # nothing to put on top; fall back quietly
    if requested != "auto":
        return requested
    if cam is not None:
        return "stack"
    with_faces = [s for s in a.samples if s.faces]
    spread = [
        s
        for s in with_faces
        if len(s.faces) >= 2 and max(b.cx for b in s.faces) - min(b.cx for b in s.faces) > 0.4
    ]
    if with_faces and len(spread) >= 0.4 * len(with_faces):
        return "full"  # people on both sides: a 9:16 crop would cut someone out
    return "crop"


def _target(s: Sample, cam: Box | None) -> float | None:
    faces = [b for b in s.faces if cam is None or not _inside(b, cam)]
    if faces:
        return max(faces, key=lambda b: b.area).cx
    return s.motion_centre(exclude=cam)


def _inside(b: Box, r: Box) -> bool:
    return r.x <= b.cx <= r.x + r.w and r.y <= b.cy <= r.y + r.h


def track(
    a: Analysis,
    win_w: float,
    *,
    cam: Box | None = None,
    dead_zone: float = 0.06,
    max_speed: float = 0.35,
) -> list[tuple[float, float]]:
    """Keyframes (t, left edge as a fraction of width) for a window `win_w` wide.

    Holds still while the subject stays near the window centre (dead zone), moves at
    most `max_speed` widths per second, and jumps at scene cuts.
    """
    if not a.samples:
        return [(0.0, (1 - win_w) / 2)]
    lo, hi = 0.0, max(0.0, 1 - win_w)

    def clamp(centre: float) -> float:
        """Left edge that centres the window on `centre`, kept inside the frame."""
        return min(max(centre - win_w / 2, lo), hi)

    first = next((x for s in a.samples if (x := _target(s, cam)) is not None), 0.5)
    left = clamp(first)
    keys = [(0.0, left)]
    prev_t = 0.0
    cuts = sorted(a.cuts)
    for s in a.samples[1:]:
        tgt = _target(s, cam)
        crossed_cut = any(prev_t < c <= s.t for c in cuts)
        if tgt is not None:
            want = clamp(tgt)
            if crossed_cut:
                left = want
            elif abs((left + win_w / 2) - tgt) > dead_zone:
                step = max_speed * (s.t - prev_t)
                left = min(max(want, left - step), left + step)
        if abs(left - keys[-1][1]) > 1e-3 or crossed_cut:
            keys.append((s.t, left))
        prev_t = s.t
    return _simplify(keys)


def _simplify(
    keys: list[tuple[float, float]], tol: float = 0.004, limit: int = 80
) -> list[tuple[float, float]]:
    """Drop keyframes that lie on the line between their neighbours (shorter ffmpeg expr)."""
    if len(keys) <= 2:
        return keys
    out = [keys[0]]
    for i in range(1, len(keys) - 1):
        (t0, x0), (t1, x1), (t2, x2) = out[-1], keys[i], keys[i + 1]
        interp = x0 + (x2 - x0) * (t1 - t0) / (t2 - t0) if t2 > t0 else x1
        if abs(interp - x1) > tol:
            out.append(keys[i])
    out.append(keys[-1])
    while len(out) > limit:  # very busy clips: keep every other point
        out = out[::2] + ([out[-1]] if out[-1] != out[::2][-1] else [])
    return out


def x_expression(keys: list[tuple[float, float]], scale_px: float) -> str:
    """Piecewise-linear ffmpeg expression in `t` for the crop's x (pixels).
    The caller puts it inside single quotes, so commas need no escaping."""
    pts = [(t, x * scale_px) for t, x in keys]
    if len(pts) == 1:
        return f"{pts[0][1]:.1f}"
    expr = f"{pts[-1][1]:.1f}"
    for (t0, x0), (t1, x1) in reversed(list(pairwise(pts))):
        if t1 - t0 < 1e-6:
            seg = f"{x0:.1f}"
        else:
            seg = f"{x0:.1f}+({x1 - x0:.1f})*(t-{t0:.3f})/{t1 - t0:.3f}"
        expr = f"if(lt(t,{t1:.3f}),{seg},{expr})"
    return expr
