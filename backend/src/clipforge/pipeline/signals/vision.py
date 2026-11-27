"""Picture signals from a small proxy video (360p, 4 fps): no AI service, all local.

- motion: mean frame difference per second -> "action" (sustained) and "impact" (sudden)
- faces: MediaPipe FaceLandmarker blendshapes (jaw open, eyes wide, smile, brows up)
  -> "reaction" when the expression jumps well above that face's recent baseline
- cuts: PySceneDetect content detector (scene changes; also used later for reframing)

Rule-based on purpose: these are hints for ranking, the AI picker judges meaning.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np

from clipforge.core.logging import get_logger
from clipforge.pipeline.signals import Spike, binned_max, merge_runs
from clipforge.pipeline.signals.audio import rolling_median

log = get_logger(__name__)

FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)
SEGMENT_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
    "selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite"
)
PROXY_FPS = 4
PROXY_HEIGHT = 360


def _download_once(url: str, dst: Path, min_bytes: int) -> Path:
    if dst.exists() and dst.stat().st_size > min_bytes:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dst.parent, suffix=".part")
    os.close(fd)
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        if os.path.getsize(tmp) <= min_bytes:
            raise RuntimeError(f"download of {dst.name} is incomplete")
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return dst


def ensure_face_model(models_dir: Path) -> Path:
    """Download MediaPipe's face landmarker (Apache-2.0, ~4 MB) once."""
    return _download_once(
        FACE_MODEL_URL, models_dir / "mediapipe" / "face_landmarker.task", 1_000_000
    )


def ensure_segment_model(models_dir: Path) -> Path:
    """Download MediaPipe's multiclass selfie segmenter (Apache-2.0, ~16 MB) once:
    cuts the streamer out of the facecam, including hair, headsets and caps."""
    return _download_once(
        SEGMENT_MODEL_URL, models_dir / "mediapipe" / "selfie_multiclass_256x256.tflite", 10_000_000
    )


@dataclass
class FrameStats:
    """Per-second series (index i covers [offset + i, offset + i + 1))."""

    offset_s: float
    motion: list[float] = field(default_factory=list)
    face: list[float] = field(default_factory=list)  # fraction of sampled frames with a face
    expression: list[float] = field(default_factory=list)  # 0..1, NaN when no face


def _expression(blendshapes: list[Any]) -> float:
    s = {b.category_name: float(b.score) for b in blendshapes}
    eyes = (s.get("eyeWideLeft", 0) + s.get("eyeWideRight", 0)) / 2
    smile = (s.get("mouthSmileLeft", 0) + s.get("mouthSmileRight", 0)) / 2
    return max(s.get("jawOpen", 0), eyes, 0.8 * smile, 0.7 * s.get("browInnerUp", 0))


class _Faces:
    def __init__(self, model: Path) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        opts = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=True,
        )
        self.landmarker = vision.FaceLandmarker.create_from_options(opts)

    def expression(self, bgr: np.ndarray, ts_ms: int) -> float | None:
        import mediapipe as mp

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        res = self.landmarker.detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts_ms
        )
        if not res.face_blendshapes:
            return None
        return _expression(res.face_blendshapes[0])

    def close(self) -> None:
        self.landmarker.close()


def analyze_frames(
    proxy: Path,
    offset_s: float,
    *,
    face_model: Path | None,
    face_every: int = 2,
    progress: Callable[[float], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> FrameStats:
    cap = cv2.VideoCapture(str(proxy))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open proxy video {proxy.name}")
    fps = cap.get(cv2.CAP_PROP_FPS) or PROXY_FPS
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    faces = _Faces(face_model) if face_model else None
    per_sec: dict[int, dict[str, list[float]]] = {}
    prev: np.ndarray | None = None
    i = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if is_cancelled and i % 20 == 0 and is_cancelled():
                raise InterruptedError
            sec = int(i / fps)
            bucket = per_sec.setdefault(sec, {"m": [], "f": [], "e": []})
            small = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY).astype(
                np.float32
            )
            if prev is not None:
                bucket["m"].append(float(np.mean(np.abs(small - prev))) / 255.0)
            prev = small
            if faces and i % face_every == 0:
                e = faces.expression(frame, int(i / fps * 1000))
                bucket["f"].append(0.0 if e is None else 1.0)
                if e is not None:
                    bucket["e"].append(e)
            i += 1
            if progress and total and i % 40 == 0:
                progress(min(99.0, i / total * 100))
    finally:
        cap.release()
        if faces:
            faces.close()
    n = (max(per_sec) + 1) if per_sec else 0
    st = FrameStats(offset_s)
    for s in range(n):
        b = per_sec.get(s, {"m": [], "f": [], "e": []})
        st.motion.append(float(np.mean(b["m"])) if b["m"] else 0.0)
        st.face.append(float(np.mean(b["f"])) if b["f"] else 0.0)
        st.expression.append(float(np.max(b["e"])) if b["e"] else float("nan"))
    return st


def moment_spikes(st: FrameStats) -> list[Spike]:
    out: list[Spike] = []
    m = np.asarray(st.motion, dtype=np.float32)
    if len(m) >= 5:
        base = np.maximum(rolling_median(m, 61), 1e-3)
        # Main test: well above the rolling baseline. The percentile floor only stops
        # tiny wiggles in very still videos; p90 would hide events that fill >10% of a
        # short clip (the event itself becomes the 90th percentile).
        p75 = float(np.percentile(m, 75))
        action = (m >= np.maximum(p75, 2.5 * base)) & (m > 0.02)
        for s, e in merge_runs(list(action), 1.0, st.offset_s, min_len=3.0):
            i0, i1 = int(s - st.offset_s), int(e - st.offset_s)
            r = float(np.max(m[i0:i1] / base[i0:i1]))
            out.append(
                Spike(
                    "moment",
                    s,
                    e,
                    min(1.0, r / 6),
                    "action",
                    {"kind": "action", "motion_x": round(r, 1)},
                )
            )
        jump = np.diff(m, prepend=m[0])
        p97 = float(np.percentile(m, 97))
        for i in np.where((jump > 4 * base) & (m >= p97) & (m > 0.04))[0]:
            t = st.offset_s + float(i)
            out.append(Spike("moment", t, t + 2, 0.6, "impact", {"kind": "impact"}))
    ex = np.asarray(st.expression, dtype=np.float32)
    has = ~np.isnan(ex)
    if has.sum() >= 5:
        filled = np.where(has, ex, np.nanmedian(ex))
        base_e = rolling_median(filled, 31)
        react = has & (filled - base_e > 0.35) & (filled > 0.5)
        for s, e in merge_runs(list(react), 1.0, st.offset_s, min_len=1.0):
            i0, i1 = int(s - st.offset_s), int(e - st.offset_s)
            peak = float(np.max(filled[i0:i1] - base_e[i0:i1]))
            out.append(
                Spike("moment", s, e, min(1.0, peak / 0.6), "reaction", {"kind": "reaction"})
            )
    return out


def cut_spikes(proxy: Path, offset_s: float, threshold: float = 27.0) -> list[Spike]:
    from scenedetect import ContentDetector, detect

    scenes = detect(str(proxy), ContentDetector(threshold=threshold, min_scene_len=4))
    return [
        Spike(
            "cut",
            offset_s + float(start.get_seconds()),
            offset_s + float(start.get_seconds()),
            0.3,
            "cut",
        )
        for start, _ in scenes[1:]
    ]


def series_curve(values: list[float], bins: int) -> list[float]:
    v = np.nan_to_num(np.asarray(values, dtype=np.float32))
    if len(v) == 0:
        return []
    hi = float(np.percentile(v, 99)) or 1.0
    return binned_max(np.clip(v / hi, 0, 1), bins)
