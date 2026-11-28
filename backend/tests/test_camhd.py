"""HD facecam: the Real-ESRGAN upscaler written as ONNX without PyTorch, the regions it
works on, and how the renderer uses its video."""

from __future__ import annotations

import io
import pickle
import sys
import types
import zipfile
from pathlib import Path

import numpy as np
import pytest

from clipforge.pipeline.render import camhd
from clipforge.pipeline.render import scene as sc
from clipforge.pipeline.render.reframe import Box
from clipforge.pipeline.render.scene_render import CutPlan, build_graph


def _weights(zero: bool = True, last_bias: float = 0.0) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(1)
    w: dict[str, np.ndarray] = {}
    n = camhd.NUM_CONV
    for i in range(n + 1):
        c_in = 3 if i == 0 else 64
        conv = rng.normal(0, 0.05, (64, c_in, 3, 3)).astype(np.float32)
        w[f"body.{2 * i}.weight"] = conv * (0 if zero else 1)
        w[f"body.{2 * i}.bias"] = np.zeros(64, np.float32)
        w[f"body.{2 * i + 1}.weight"] = np.full(64, 0.25, np.float32)
    last = 2 * (n + 1)
    w[f"body.{last}.weight"] = np.zeros((48, 64, 3, 3), np.float32)
    w[f"body.{last}.bias"] = np.full(48, last_bias, np.float32)
    return w


def _run(model: bytes, x: np.ndarray) -> np.ndarray:
    import onnxruntime as ort

    s = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
    return np.asarray(s.run(["output"], {"input": x})[0])


def test_the_graph_is_valid_onnx_and_adds_the_upscaled_input() -> None:
    """With the learned part silent, the network is a 4x nearest-neighbour upscale; the
    last bias then shows up in every output pixel."""
    x = np.random.default_rng(0).random((1, 3, 6, 5), dtype=np.float32)
    y = _run(camhd.build_onnx(_weights()), x)
    assert y.shape == (1, 3, 24, 20)
    assert np.allclose(y, x.repeat(4, axis=2).repeat(4, axis=3), atol=1e-6)
    y2 = _run(camhd.build_onnx(_weights(last_bias=0.1)), x)
    assert np.allclose(y2 - y, 0.1, atol=1e-5)
    half = _run(camhd.build_onnx(_weights(zero=False), half=True), x)
    full = _run(camhd.build_onnx(_weights(zero=False)), x)
    assert np.allclose(half, full, atol=2e-2)


class _Pid:
    def __init__(self, pid: tuple[object, ...]) -> None:
        self.pid = pid


def _fake_torch_zip(path: Path, state: dict[str, np.ndarray], extra: object = None) -> None:
    """Write a file laid out like torch.save (zip + data.pkl + raw storages)."""
    tmod = types.ModuleType("torch")
    umod = types.ModuleType("torch._utils")

    class FloatStorage:
        pass

    def _rebuild_tensor_v2(*a: object) -> None:  # pragma: no cover - never called
        return None

    FloatStorage.__module__, FloatStorage.__qualname__ = "torch", "FloatStorage"
    _rebuild_tensor_v2.__module__ = "torch._utils"
    _rebuild_tensor_v2.__qualname__ = "_rebuild_tensor_v2"
    tmod.FloatStorage = FloatStorage  # type: ignore[attr-defined]
    umod._rebuild_tensor_v2 = _rebuild_tensor_v2  # type: ignore[attr-defined]
    saved = {k: sys.modules.get(k) for k in ("torch", "torch._utils")}
    sys.modules["torch"], sys.modules["torch._utils"] = tmod, umod
    storages: dict[str, bytes] = {}

    class Tensor:
        def __init__(self, a: np.ndarray) -> None:
            self.a = np.asarray(a, dtype=np.float32)

        def __reduce__(self) -> tuple[object, tuple[object, ...]]:
            key = str(len(storages))
            storages[key] = self.a.astype("<f4").tobytes()
            stor = _Pid(("storage", FloatStorage, key, "cpu", self.a.size))
            return _rebuild_tensor_v2, (stor, 0, self.a.shape, (), False, {})

    class Pickler(pickle.Pickler):
        def persistent_id(self, obj: object) -> object:
            return obj.pid if isinstance(obj, _Pid) else None

    try:
        buf = io.BytesIO()
        body: dict[str, object] = {k: Tensor(v) for k, v in state.items()}
        if extra is not None:
            body["extra"] = extra
        Pickler(buf, protocol=2).dump({"params": body})
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("model/data.pkl", buf.getvalue())
            for k, b in storages.items():
                zf.writestr(f"model/data/{k}", b)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_weights_are_read_from_a_torch_file_without_torch(tmp_path: Path) -> None:
    state = {"a.weight": np.arange(6, dtype=np.float32).reshape(2, 3), "a.bias": np.ones(2)}
    _fake_torch_zip(tmp_path / "m.pth", state)
    got = camhd.load_weights(tmp_path / "m.pth")
    assert set(got) == {"a.weight", "a.bias"}
    assert np.array_equal(got["a.weight"], state["a.weight"])


def test_a_model_file_with_other_objects_is_refused(tmp_path: Path) -> None:
    _fake_torch_zip(tmp_path / "bad.pth", {"a": np.ones(2)}, extra=Path("x"))
    with pytest.raises(pickle.UnpicklingError):
        camhd.load_weights(tmp_path / "bad.pth")


def test_regions_cover_every_tile_crop_of_a_small_cam() -> None:
    cam = Box(0.02, 0.41, 0.10, 0.17)  # a real overlay: ~260 px wide in a 1440p stream
    (r,) = camhd.hd_regions([cam], 2560, 1440)
    assert r is not None and r.w <= camhd.MAX_REGION_W
    assert max(r.out_w, r.out_h) <= camhd.MAX_SIDE and r.out_w >= 3 * r.w
    for aspect in (0.5, 9 / 16, 1, 4 / 3, 16 / 9, 3, 5):
        rect = sc.cover_crop((cam.x, cam.y, cam.w, cam.h), aspect, 2560, 1440, sc.CAM_MAX_GROW)
        assert camhd.hd_crop(rect, r) is not None, aspect
    big = Box(0.0, 0.0, 0.6, 0.8)  # a camera shot: plenty of pixels already
    assert camhd.hd_regions([big], 1920, 1080) == [None]


def test_crops_map_into_the_hd_video() -> None:
    r = camhd.HDRegion(100, 50, 400, 300, 1600, 1200)
    assert camhd.hd_crop((100, 50, 400, 300), r) == (0, 0, 1600, 1200)
    assert camhd.hd_crop((200, 100, 100, 100), r) == (400, 200, 400, 400)
    assert camhd.hd_crop((0, 0, 100, 100), r) is None  # outside: use the source


def _graph(tmp: Path, *, enhance: bool, hd: bool) -> str:
    cam = Box(0.70, 0.05, 0.12, 0.2)
    (r,) = camhd.hd_regions([cam], 1920, 1080)
    assert r is not None
    plan = CutPlan(
        1920,
        1080,
        10.0,
        cam,
        [(0.0, 0.5)],
        [],
        [],
        cams=[cam],
        camhd=[(tmp / "camhd0.mp4", r)] if hd else [],
    )
    scene = sc.default_scene("streamer_first", sc.Ctx(10.0, []))
    scene.regions.cam_bg = "original"
    scene.regions.cam_enhance = enhance
    return build_graph(
        scene, plan, tmp, words=[], keywords=[], values={}, image_path=lambda _: None
    ).graph


def test_the_renderer_takes_the_cam_from_the_hd_video(tmp_path: Path) -> None:
    g = _graph(tmp_path, enhance=True, hd=True)
    assert "[sc0]nullsink" in g and "hqdn3d" not in g  # the source crop is not used
    assert "hqdn3d" in _graph(tmp_path, enhance=True, hd=False)  # no HD video: as before
    assert "nullsink" not in _graph(tmp_path, enhance=False, hd=True)  # sharpening off
