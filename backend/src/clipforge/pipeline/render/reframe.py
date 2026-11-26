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
from typing import Any

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
    mouths: list[float] = field(default_factory=list)  # mouth opening per face (0..1)

    def motion_centre(self, exclude: Box | list[Box] | None = None) -> float | None:
        """Centre of motion, optionally ignoring regions (facecams: a talking
        streamer moves constantly and would drag the game crop onto the cam)."""
        boxes = [exclude] if isinstance(exclude, Box) else (exclude or [])
        if self.motion is None or not boxes:
            return self.motion_x
        g = self.motion.copy()
        for b in boxes:
            x0, x1 = int(b.x * GRID_W), int(np.ceil((b.x + b.w) * GRID_W))
            y0, y1 = int(b.y * GRID_H), int(np.ceil((b.y + b.h) * GRID_H))
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
SCAN_W = 1920  # small-face scan works on frames scaled down to this width
SCAN_TILE = 480  # px; a facecam face (~80-130 px) is big enough for the detector here
SCAN_EVERY = 4  # whole-frame tile scan every 4th sample (1/s); in between, known spots only


def _tile_starts(size: int, tile: int) -> list[int]:
    if size <= tile:
        return [0]
    step = tile * 2 // 3
    starts = list(range(0, size - tile + 1, step))
    if starts[-1] != size - tile:
        starts.append(size - tile)
    return starts


def _faces_from(res: Any, ox: float, oy: float, sw: float, sh: float) -> list[tuple[Box, float]]:
    """Landmarker result -> (box, mouth opening); the image covered (ox, oy, sw, sh) of
    the frame (fractions)."""
    out = []
    for pts in res.face_landmarks:
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        x0, x1 = max(0.0, min(xs)), min(1.0, max(xs))
        y0, y1 = max(0.0, min(ys)), min(1.0, max(ys))
        if x1 <= x0 or y1 <= y0:
            continue
        face_h = max(1e-6, abs(pts[152].y - pts[10].y)) if len(pts) > 152 else 1.0
        gap = abs(pts[14].y - pts[13].y) if len(pts) > 14 else 0.0
        box = Box(ox + x0 * sw, oy + y0 * sh, (x1 - x0) * sw, (y1 - y0) * sh)
        out.append((box, min(1.0, gap / face_h)))
    return out


def _same_face(a: Box, b: Box) -> bool:
    return abs(a.cx - b.cx) < 0.6 * max(a.w, b.w) and abs(a.cy - b.cy) < 0.6 * max(a.h, b.h)


class _FaceFinder:
    """MediaPipe's detector only finds faces that fill a good part of the image, so a
    streamer's facecam (a ~100 px face in a 1080p frame) is invisible to a whole-frame
    pass. Frames are therefore also scanned in overlapping tiles: the whole frame once
    a second, and in between only a tile around each small face found by that scan."""

    def __init__(self, model: Path) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        def make(mode: Any) -> Any:
            return vision.FaceLandmarker.create_from_options(
                vision.FaceLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(model)),
                    running_mode=mode,
                    num_faces=4,
                    min_face_detection_confidence=0.5,
                )
            )

        self.lm = make(vision.RunningMode.VIDEO)  # big faces (people on camera)
        self.tiles = make(vision.RunningMode.IMAGE)  # small faces (facecams)
        self.calls = 0
        self.spots: list[tuple[int, int]] = []  # tile corners centred on small faces

    def find(self, bgr: np.ndarray, ts_ms: int) -> tuple[list[Box], list[float]]:
        """Face boxes and how open each mouth is (lip gap / face height): a mouth that
        keeps opening and closing tells who is talking."""
        import mediapipe as mp

        def image(a: np.ndarray) -> Any:
            return mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(a))

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        found = _faces_from(self.lm.detect_for_video(image(rgb), ts_ms), 0, 0, 1, 1)
        h, w = rgb.shape[:2]
        if w > SCAN_W:
            rgb = cv2.resize(rgb, (SCAN_W, round(h * SCAN_W / w)), interpolation=cv2.INTER_AREA)
            h, w = rgb.shape[:2]
        tw, th = min(SCAN_TILE, w), min(SCAN_TILE, h)
        full_scan = self.calls % SCAN_EVERY == 0 or not self.spots
        self.calls += 1
        if full_scan:
            windows = [(x, y) for y in _tile_starts(h, th) for x in _tile_starts(w, tw)]
        else:  # in between, only look where faces were last seen (facecams stay put)
            windows = self.spots
        small: list[tuple[Box, float]] = []
        for x, y in windows:
            res = self.tiles.detect(image(rgb[y : y + th, x : x + tw]))
            small += _faces_from(res, x / w, y / h, tw / w, th / h)
        # overlapping tiles see a face more than once: keep the most complete view
        kept: list[tuple[Box, float]] = []
        for box, mouth in sorted(small, key=lambda f: -f[0].area):
            if not any(_same_face(box, b) for b, _ in found + kept):
                kept.append((box, mouth))
        if full_scan:
            self.spots = [
                (
                    min(max(0, round(b.cx * w - tw / 2)), w - tw),
                    min(max(0, round(b.cy * h - th / 2)), h - th),
                )
                for b, _ in kept
            ]
        found += kept
        return [b for b, _ in found], [m for _, m in found]

    def close(self) -> None:
        self.lm.close()
        self.tiles.close()


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
                faces, mouths = finder.find(frame, int(t * 1000)) if finder else ([], [])
                samples.append(Sample(t, faces, mx, grid, mouths))
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


# ------------------------------------------------------------------ people
PERSON_MIN_SHARE = 0.3  # on screen at least this share of the clip to count as a person
CAMERA_MIN_SHARE = 0.5  # people filmed by the main camera (no facecam overlay)
MAX_PEOPLE = 3
WIN_9X16 = 0.316  # a 9:16 window on 16:9 footage, as a fraction of the width
# A face in a facecam overlay is tiny (about 1% of the frame); bigger steady faces are
# people filmed by the main camera.
OVERLAY_FACE_MAX = 0.025


@dataclass
class Person:
    """One face followed through the clip (matched by position sample to sample)."""

    seen: dict[int, tuple[Box, float]] = field(default_factory=dict)  # sample -> (box, mouth)
    last: Box = field(default_factory=lambda: Box(0, 0, 0, 0))

    def add(self, i: int, b: Box, mouth: float) -> None:
        self.seen[i] = (b, mouth)
        self.last = b

    def share(self, n: int) -> float:
        return len(self.seen) / max(1, n)

    def median(self) -> Box:
        bs = [b for b, _ in self.seen.values()]
        return Box(
            float(np.median([b.x for b in bs])),
            float(np.median([b.y for b in bs])),
            float(np.median([b.w for b in bs])),
            float(np.median([b.h for b in bs])),
        )

    def steady(self) -> bool:
        bs = [b for b, _ in self.seen.values()]
        return float(np.std([b.cx for b in bs])) < 0.03 and float(np.std([b.cy for b in bs])) < 0.03

    def activity(self, i: int, half: int = 4) -> float:
        """How much the mouth moves around sample i (talking); 0 when unknown."""
        m = [self.seen[k][1] for k in range(i - half, i + half + 1) if k in self.seen]
        return float(np.std(m)) if len(m) >= 3 else 0.0

    def talk(self) -> float:
        m = [x for _, x in self.seen.values()]
        return float(np.std(m)) if len(m) >= 3 else 0.0


@dataclass
class People:
    """Who is on screen and how to show them.

    kind
    - overlay: streamer facecam(s) on top of gameplay, one box per cam overlay (two
      streamers sharing one cam end up in one box, two separate cams in two)
    - camera : people filmed by the main camera (IRL, podcasts, couch streams)
    - none   : nobody steady enough to show in a facecam panel
    """

    kind: str
    cams: list[Box]  # what a facecam panel shows, left to right
    primary: int = 0  # the cam of whoever talks the most
    persons: list[Person] = field(default_factory=list)


def track_faces(samples: list[Sample]) -> list[Person]:
    """Link faces across samples by position, biggest faces first."""
    people: list[Person] = []
    for i, s in enumerate(samples):
        mouths = s.mouths if len(s.mouths) == len(s.faces) else [0.0] * len(s.faces)
        taken: set[int] = set()
        for b, m in sorted(zip(s.faces, mouths, strict=True), key=lambda f: -f[0].area):
            best, best_d = -1, 1e9
            for k, p in enumerate(people):
                if k in taken:
                    continue
                last = p.last
                d = abs(last.cx - b.cx) + abs(last.cy - b.cy)
                ratio = max(last.area, b.area) / max(1e-9, min(last.area, b.area))
                if d < max(0.08, 0.6 * max(last.w, b.w)) and ratio < 2.5 and d < best_d:
                    best, best_d = k, d
            if best < 0:
                people.append(Person())
                best = len(people) - 1
            taken.add(best)
            people[best].add(i, b, m)
    return people


def _overlaps(a: Box, b: Box) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def _union(boxes: list[Box]) -> Box:
    x0, y0 = min(b.x for b in boxes), min(b.y for b in boxes)
    x1, y1 = max(b.x + b.w for b in boxes), max(b.y + b.h for b in boxes)
    return Box(x0, y0, x1 - x0, y1 - y0)


def _groups(items: list[tuple[Box, Person]]) -> list[tuple[Box, list[Person]]]:
    """Merge people whose (expanded) boxes touch: they share one cam or one shot."""
    groups = [(b, [p]) for b, p in items]
    merged = True
    while merged:
        merged = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if _overlaps(groups[i][0], groups[j][0]):
                    a, b = groups[i], groups.pop(j)
                    groups[i] = (_union([a[0], b[0]]), a[1] + b[1])
                    merged = True
                    break
            if merged:
                break
    return groups


def _off_centre(b: Box) -> bool:
    return abs(b.cx - 0.5) > 0.15 or abs(b.cy - 0.5) > 0.15


def find_people(samples: list[Sample]) -> People:
    """Facecam overlays (any number of streamers) or people on the main camera."""
    n = len(samples)
    if n < 4:
        return People("none", [])
    persons = [p for p in track_faces(samples) if p.share(n) >= PERSON_MIN_SHARE]
    overlay = [
        p
        for p in persons
        if p.steady() and p.median().area < OVERLAY_FACE_MAX and _off_centre(p.median())
    ]
    if overlay:
        kind = "overlay"
        groups = _groups([(p.median().expand(2.6, 2.2), p) for p in overlay])
    else:
        persons = [p for p in persons if p.share(n) >= CAMERA_MIN_SHARE]
        if not persons:
            return People("none", [])
        kind = "camera"
        groups = _groups([(p.median().expand(2.4, 2.4), p) for p in persons])
    groups.sort(key=lambda g: -max(p.share(n) for p in g[1]))
    groups = sorted(groups[:MAX_PEOPLE], key=lambda g: g[0].cx)
    talk = [max(p.talk() * p.share(n) for p in g[1]) for g in groups]
    if any(talk):
        primary = int(np.argmax(talk))
    else:
        primary = int(np.argmax([max(p.share(n) for p in g[1]) for g in groups]))
    return People(kind, [g[0] for g in groups], primary, persons)


def detect_cam(samples: list[Sample]) -> Box | None:
    """The main facecam overlay, if any (``find_people`` has all of them)."""
    pp = find_people(samples)
    return pp.cams[pp.primary] if pp.kind == "overlay" else None


def speakers(samples: list[Sample], persons: list[Person], switch: float = 1.4) -> list[int | None]:
    """Who talks at each sample (index into persons). Changes only when someone else
    clearly talks more, so the crop does not flick between people."""
    out: list[int | None] = []
    cur: int | None = None
    for i in range(len(samples)):
        act = [p.activity(i) if i in p.seen else -1.0 for p in persons]
        if not act or max(act) < 0:
            out.append(cur)
            continue
        best = int(np.argmax(act))
        lost = cur is None or act[cur] < 0
        if lost or (best != cur and act[best] > act[cur] * switch + 0.004):  # type: ignore[index]
            cur = best
        out.append(cur)
    return out


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


def _target(s: Sample, cams: list[Box]) -> float | None:
    faces = [b for b in s.faces if not any(_inside(b, c) for c in cams)]
    if faces:
        return max(faces, key=lambda b: b.area).cx
    return s.motion_centre(exclude=cams or None)


def _inside(b: Box, r: Box) -> bool:
    return r.x <= b.cx <= r.x + r.w and r.y <= b.cy <= r.y + r.h


def _camera_targets(a: Analysis, pp: People) -> list[tuple[float, float | None]]:
    """People on the main camera: keep the whole group in the shot when it fits a 9:16
    window, otherwise follow whoever is talking."""
    talking = speakers(a.samples, pp.persons)
    out: list[tuple[float, float | None]] = []
    for i, s in enumerate(a.samples):
        if not s.faces:
            out.append((s.t, s.motion_centre()))
            continue
        lo = min(b.x for b in s.faces)
        hi = max(b.x + b.w for b in s.faces)
        if hi - lo <= WIN_9X16 * 0.85:
            out.append((s.t, (lo + hi) / 2))
            continue
        k = talking[i]
        seen = pp.persons[k].seen.get(i) if k is not None else None
        out.append((s.t, seen[0].cx if seen else max(s.faces, key=lambda b: b.area).cx))
    return out


def sample_targets(a: Analysis, people: People | Box | None) -> list[tuple[float, float | None]]:
    """(t, horizontal centre to follow) per analysis sample; stored with the cut so any
    template can compute its own crop path later without re-analysing the video.
    Gameplay with facecams follows the action (cams masked out); people on camera are
    framed together, or the one talking when they do not fit."""
    if isinstance(people, People) and people.kind == "camera":
        return _camera_targets(a, people)
    if isinstance(people, People):
        cams = people.cams if people.kind == "overlay" else []
    else:
        cams = [people] if people is not None else []
    return [(s.t, _target(s, cams)) for s in a.samples]


def action_box(targets: list[tuple[float, float | None]]) -> Box:
    """A close-up of where the action mostly is, for a facecam panel with no facecam."""
    xs = [x for _, x in targets if x is not None]
    cx = float(np.median(xs)) if xs else 0.5
    w, h = 0.45, 0.6
    return Box(min(max(cx - w / 2, 0.0), 1 - w), 0.2, w, h)


def track(
    a: Analysis,
    win_w: float,
    *,
    cam: Box | None = None,
    dead_zone: float = 0.06,
    max_speed: float = 0.35,
) -> list[tuple[float, float]]:
    return track_targets(
        sample_targets(a, cam), a.cuts, win_w, dead_zone=dead_zone, max_speed=max_speed
    )


def track_targets(
    targets: list[tuple[float, float | None]],
    cuts: list[float],
    win_w: float,
    *,
    dead_zone: float = 0.06,
    max_speed: float = 0.35,
) -> list[tuple[float, float]]:
    """Keyframes (t, left edge as a fraction of width) for a window `win_w` wide.

    Holds still while the subject stays near the window centre (dead zone), moves at
    most `max_speed` widths per second, and jumps at scene cuts. The browser preview
    has a line-by-line port of this (studio/track.ts).
    """
    if not targets:
        return [(0.0, (1 - win_w) / 2)]
    lo, hi = 0.0, max(0.0, 1 - win_w)

    def clamp(centre: float) -> float:
        """Left edge that centres the window on `centre`, kept inside the frame."""
        return min(max(centre - win_w / 2, lo), hi)

    first = next((x for _, x in targets if x is not None), 0.5)
    left = clamp(first)
    keys = [(0.0, left)]
    prev_t = 0.0
    cuts = sorted(cuts)
    for t, tgt in targets[1:]:
        crossed_cut = any(prev_t < c <= t for c in cuts)
        if tgt is not None:
            want = clamp(tgt)
            if crossed_cut:
                left = want
            elif abs((left + win_w / 2) - tgt) > dead_zone:
                step = max_speed * (t - prev_t)
                left = min(max(want, left - step), left + step)
        if abs(left - keys[-1][1]) > 1e-3 or crossed_cut:
            keys.append((t, left))
        prev_t = t
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
