"""HD facecam: an AI upscaler for the streamer's cam.

A facecam overlay is small in the stream (often ~500x300 px in a 1440p frame) and the
Short enlarges it 3-4x, so a plain resize looks soft and blocky. Here every frame of
each cam region goes through Real-ESRGAN (realesr-general-x4v3, BSD-3, ~5 MB), which
restores faces, hair and edges, and is written as its own video. The renderer then
crops the facecam tile from that video instead of the source. Made once per cut, like
the matte.

No PyTorch: the official weights are read straight from the .pth file (a zip of raw
tensors; only plain tensor records are accepted while unpickling) and written as a
small ONNX graph that onnxruntime runs on the GPU (DirectML on Windows) or the CPU.
"""

from __future__ import annotations

import pickle
import queue
import subprocess
import threading
import zipfile
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from clipforge.core import ffmpeg
from clipforge.core.logging import get_logger
from clipforge.pipeline.render.reframe import Box

log = get_logger(__name__)

MODEL_URL = (
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth"
)
SCALE = 4
NUM_CONV = 32
REGION_GROW = 1.35  # a tile crop grows a cam box by at most 1.3 (scene.CAM_MAX_GROW)
MAX_REGION_W = 900  # a cam this wide (in source pixels) is sharp enough already
MAX_SIDE = 1600  # the HD video's longer side
OUT_FPS = 30


# ------------------------------------------------------------------ weights


class _SafeUnpickler(pickle.Unpickler):
    """Reads a PyTorch state dict without PyTorch: only tensor records are allowed."""

    def __init__(self, f: Any, zf: zipfile.ZipFile, root: str) -> None:
        super().__init__(f)
        self.zf, self.root = zf, root

    def find_class(self, module: str, name: str) -> Any:
        if (module, name) == ("torch._utils", "_rebuild_tensor_v2"):
            return _rebuild_tensor
        if (module, name) == ("collections", "OrderedDict"):
            return OrderedDict
        if module == "torch" and name == "FloatStorage":
            return np.float32
        raise pickle.UnpicklingError(f"unexpected object in the model file: {module}.{name}")

    def persistent_load(self, pid: Any) -> np.ndarray:
        kind, dtype, key, _location, _numel = pid
        if kind != "storage" or dtype is not np.float32:
            raise pickle.UnpicklingError("unexpected storage in the model file")
        return np.frombuffer(self.zf.read(f"{self.root}/data/{key}"), dtype="<f4")


def _rebuild_tensor(storage: np.ndarray, offset: int, size: tuple[int, ...], stride: Any,
                    *_: Any) -> np.ndarray:  # fmt: skip
    n = int(np.prod(size)) if size else 1
    return storage[offset : offset + n].reshape(size).astype(np.float32)


def load_weights(pth: Path) -> dict[str, np.ndarray]:
    with zipfile.ZipFile(pth) as zf:
        pkl = next(n for n in zf.namelist() if n.endswith("/data.pkl"))
        root = pkl.rsplit("/", 1)[0]
        with zf.open(pkl) as f:
            obj = _SafeUnpickler(f, zf, root).load()
    sd = obj.get("params_ema") or obj.get("params") or obj
    return {k: np.asarray(v, dtype=np.float32) for k, v in sd.items()}


# ------------------------------------------------------------------ ONNX writer
# A minimal protobuf encoder for the few ONNX messages the network needs.


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(num: int, wire: int, payload: bytes | int) -> bytes:
    key = _varint((num << 3) | wire)
    if wire == 0:
        assert isinstance(payload, int)
        return key + _varint(payload)
    assert isinstance(payload, bytes)
    return key + _varint(len(payload)) + payload


def _s(num: int, text: str) -> bytes:
    return _field(num, 2, text.encode())


def _attr_ints(name: str, vals: Sequence[int]) -> bytes:
    return _s(1, name) + b"".join(_field(8, 0, v) for v in vals) + _field(20, 0, 7)


def _attr_int(name: str, val: int) -> bytes:
    return _s(1, name) + _field(3, 0, val) + _field(20, 0, 2)


def _attr_str(name: str, val: str) -> bytes:
    return _s(1, name) + _field(4, 2, val.encode()) + _field(20, 0, 3)


def _node(op: str, ins: Sequence[str], outs: Sequence[str], attrs: Sequence[bytes] = ()) -> bytes:
    body = b"".join(_s(1, i) for i in ins) + b"".join(_s(2, o) for o in outs)
    body += _s(4, op) + b"".join(_field(5, 2, a) for a in attrs)
    return _field(1, 2, body)


def _init(name: str, arr: np.ndarray, half: bool = False) -> bytes:
    a = np.ascontiguousarray(arr, dtype="<f2" if half else "<f4")
    body = b"".join(_field(1, 0, d) for d in a.shape) + _field(2, 0, 10 if half else 1)
    body += _s(8, name) + _field(9, 2, a.tobytes())
    return _field(5, 2, body)


def _value(num: int, name: str) -> bytes:
    dims = [_field(1, 2, _s(2, d)) for d in ("n", "c", "h", "w")]
    dims[1] = _field(1, 2, _field(1, 0, 3))
    shape = b"".join(dims)
    tensor = _field(1, 0, 1) + _field(2, 2, shape)
    return _field(num, 2, _s(1, name) + _field(2, 2, _field(1, 2, tensor)))


def build_onnx(w: dict[str, np.ndarray], half: bool = False) -> bytes:
    """SRVGGNetCompact (Real-ESRGAN's small model): conv + PReLU x (1 + NUM_CONV),
    a last conv, pixel shuffle, plus the nearest-upsampled input. `half` computes in
    float16 inside (no faster with DirectML on an RTX 4050, so off); input and output
    stay float32."""
    nodes, inits = [], []
    to = 10 if half else 1
    nodes.append(_node("Cast", ["input"], ["x"], [_attr_int("to", to)]))
    x = "x"
    for i in range(NUM_CONV + 1):
        c, p = 2 * i, 2 * i + 1
        inits += [_init(f"w{c}", w[f"body.{c}.weight"], half),
                  _init(f"b{c}", w[f"body.{c}.bias"], half)]  # fmt: skip
        inits.append(_init(f"a{p}", w[f"body.{p}.weight"].reshape(-1, 1, 1), half))
        conv = f"c{c}"
        nodes.append(_node("Conv", [x, f"w{c}", f"b{c}"], [conv], [_attr_ints("pads", [1] * 4)]))
        nodes.append(_node("PRelu", [conv, f"a{p}"], [f"r{p}"]))
        x = f"r{p}"
    last = 2 * (NUM_CONV + 1)
    inits += [
        _init("wl", w[f"body.{last}.weight"], half),
        _init("bl", w[f"body.{last}.bias"], half),
    ]
    nodes.append(_node("Conv", [x, "wl", "bl"], ["cl"], [_attr_ints("pads", [1] * 4)]))
    nodes.append(_node("DepthToSpace", ["cl"], ["up"], [_attr_int("blocksize", SCALE),
                                                         _attr_str("mode", "CRD")]))  # fmt: skip
    inits.append(_init("scales", np.array([1, 1, SCALE, SCALE], np.float32)))
    nodes.append(_node("Resize", ["x", "", "scales"], ["base"], [_attr_str("mode", "nearest")]))
    nodes.append(_node("Add", ["up", "base"], ["sum"]))
    nodes.append(_node("Cast", ["sum"], ["output"], [_attr_int("to", 1)]))
    graph = b"".join(nodes) + _s(2, "srvgg") + b"".join(inits)
    graph += _value(11, "input") + _value(12, "output")
    opset = _field(8, 2, _s(1, "") + _field(2, 0, 17))
    return _field(1, 0, 8) + _s(2, "clipforge") + opset + _field(7, 2, graph)


def ensure_model(models_dir: Path) -> Path:
    """The upscaler as ONNX (downloads the official weights once, ~5 MB)."""
    from clipforge.pipeline.signals.vision import _download_once

    onnx = models_dir / "realesrgan" / "realesr-general-x4v3.onnx"
    if onnx.exists() and onnx.stat().st_size > 1_000_000:
        return onnx
    pth = _download_once(
        MODEL_URL, models_dir / "realesrgan" / "realesr-general-x4v3.pth", 1_000_000
    )
    tmp = onnx.with_suffix(".part")
    tmp.write_bytes(build_onnx(load_weights(pth)))
    tmp.replace(onnx)
    return onnx


# ------------------------------------------------------------------ runtime


class Upscaler:
    def __init__(self, model: Path) -> None:
        import onnxruntime as ort

        want = ["DmlExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]
        have = set(ort.get_available_providers())
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(model), opts, providers=[p for p in want if p in have]
        )
        self.on_gpu = self.session.get_providers()[0] != "CPUExecutionProvider"

    def raw(self, rgb: np.ndarray) -> np.ndarray:
        """uint8 HxWx3 -> float32 1x3x(4H)x(4W), 0..1 (not clipped)."""
        x = (rgb.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
        (y,) = self.session.run(["output"], {"input": x})
        return np.asarray(y)

    def __call__(self, rgb: np.ndarray) -> np.ndarray:
        """uint8 HxWx3 -> uint8 (4H)x(4W)x3."""
        y = self.raw(rgb)
        out: np.ndarray = (np.clip(y[0], 0, 1).transpose(1, 2, 0) * 255 + 0.5).astype(np.uint8)
        return out


@dataclass(frozen=True)
class HDRegion:
    """A cam region in source pixels and the size of its HD video."""

    x: int
    y: int
    w: int
    h: int
    out_w: int
    out_h: int


def _even(v: float) -> int:
    return max(2, int(v) // 2 * 2)


def hd_regions(cams: Sequence[Box], src_w: int, src_h: int) -> list[HDRegion | None]:
    """Per cam: the source region to upscale, or None when the cam is big enough."""
    out: list[HDRegion | None] = []
    for c in cams:
        # Like scene.cover_crop: grown around the box's centre and pushed back inside
        # the frame (not cut), so a tile crop near the frame edge still fits.
        w = _even(min(c.w * src_w * REGION_GROW, src_w))
        h = _even(min(c.h * src_h * REGION_GROW, src_h))
        cx, cy = (c.x + c.w / 2) * src_w, (c.y + c.h / 2) * src_h
        x = int(min(max(cx - w / 2, 0), src_w - w))
        y = int(min(max(cy - h / 2, 0), src_h - h))
        if w > MAX_REGION_W or w < 32 or h < 32:
            out.append(None)
            continue
        k = min(SCALE, MAX_SIDE / max(w, h))
        out.append(HDRegion(x, y, w, h, _even(w * k), _even(h * k)))
    return out


def build_hd(
    video: Path,
    region: HDRegion,
    out: Path,
    *,
    duration: float,
    upscaler: Upscaler,
    is_cancelled: Callable[[], bool] = lambda: False,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    import cv2

    r = region
    exe = ffmpeg._exe("ffmpeg")
    reader = subprocess.Popen(
        [exe, "-hide_banner", "-loglevel", "error", "-i", str(video), "-an",
         "-vf", f"fps={OUT_FPS},crop={r.w}:{r.h}:{r.x}:{r.y}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    writer = subprocess.Popen(
        [exe, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{r.out_w}x{r.out_h}",
         "-r", str(OUT_FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "fast", "-crf", "14",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )  # fmt: skip
    err: list[bytes] = []
    drain = threading.Thread(target=lambda: err.append(writer.stderr.read()), daemon=True)  # type: ignore[union-attr]
    drain.start()
    size = r.w * r.h * 3
    n_frames = max(1, round(duration * OUT_FPS))
    i = 0
    # The GPU works on frame n while another thread converts and writes frame n-1.
    todo: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=4)
    failed: list[BaseException] = []

    def write() -> None:
        try:
            assert writer.stdin is not None
            while (y := todo.get()) is not None:
                up = (np.clip(y[0], 0, 1).transpose(1, 2, 0) * 255 + 0.5).astype(np.uint8)
                if up.shape[:2] != (r.out_h, r.out_w):
                    up = cv2.resize(up, (r.out_w, r.out_h), interpolation=cv2.INTER_AREA)
                writer.stdin.write(np.ascontiguousarray(up).tobytes())
        except BaseException as e:
            failed.append(e)
            while todo.get() is not None:  # let the producer finish
                pass

    out_thread = threading.Thread(target=write, daemon=True)
    out_thread.start()
    try:
        assert reader.stdout is not None and writer.stdin is not None
        try:
            while not failed:
                buf = reader.stdout.read(size)
                if len(buf) < size:
                    break
                if is_cancelled():
                    raise ffmpeg.FFmpegCancelledError("cancelled")
                todo.put(upscaler.raw(np.frombuffer(buf, np.uint8).reshape(r.h, r.w, 3)))
                i += 1
                if on_progress and i % 15 == 0:
                    on_progress(min(99.0, i / n_frames * 100))
        finally:
            todo.put(None)
            out_thread.join()
        if failed:
            raise failed[0]
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
    if writer.returncode != 0 or i == 0:
        detail = b"".join(err).decode(errors="replace")[-300:]
        raise ffmpeg.FFmpegError(f"HD facecam encoding failed: {detail or 'no frames'}")


def hd_crop(rect: tuple[int, int, int, int], region: HDRegion) -> tuple[int, int, int, int] | None:
    """A source-pixel crop in HD-video pixels; None when it reaches outside the region
    (the renderer then crops the source as before)."""
    x, y, w, h = rect
    r = region
    if x < r.x - 2 or y < r.y - 2 or x + w > r.x + r.w + 2 or y + h > r.y + r.h + 2:
        return None
    fx, fy = r.out_w / r.w, r.out_h / r.h
    cw = min(r.out_w, max(2, int(w * fx) // 2 * 2))
    ch = min(r.out_h, max(2, int(h * fy) // 2 * 2))
    cx = min(max(0, int((x - r.x) * fx)), r.out_w - cw)
    cy = min(max(0, int((y - r.y) * fy)), r.out_h - ch)
    return cx, cy, cw, ch
