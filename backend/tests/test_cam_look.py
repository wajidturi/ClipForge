"""Facecam look: person cut-out (matte), backgrounds behind the streamer, the sharper
enlarged cam, and the HDR grade."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from clipforge.core import ffmpeg
from clipforge.pipeline.render import matte, raster, reframe
from clipforge.pipeline.render import scene as sc
from clipforge.pipeline.render.reframe import Box
from clipforge.pipeline.render.scene_render import CutPlan, build_graph
from clipforge.pipeline.signals import vision as vision_sig
from clipforge.services import cuts

from .media import needs_ffmpeg
from .test_render_flow import client, media_path, offline_faces, render, run_jobs, seed_short

__all__ = ["client", "offline_faces"]

CAM = Box(0.70, 0.05, 0.25, 0.35)


class FakeSegmenter:
    """Says the left half of every region is a person."""

    def person(self, rgb: np.ndarray, ts_ms: int) -> np.ndarray:
        p = np.zeros(rgb.shape[:2], np.float32)
        p[:, : rgb.shape[1] // 2] = 1.0
        return p

    def close(self) -> None:
        pass


def _graph(
    tmp: Path, *, bg: str, kind: str = "overlay", matte_file: bool = True, **fx: object
) -> str:
    plan = CutPlan(
        1920,
        1080,
        10.0,
        CAM,
        [(0.0, 0.5)],
        [],
        [],
        cams=[CAM],
        cam_kind=kind,
        matte=tmp / "matte.mp4" if matte_file else None,
        matte_size=(1280, 720),
    )
    scene = sc.default_scene("streamer_first", sc.Ctx(10.0, []))
    scene.regions.cam_bg = bg  # type: ignore[assignment]
    for k, v in fx.items():
        setattr(scene.effects if k == "color" else scene.regions, k, v)
    return build_graph(
        scene, plan, tmp, words=[], keywords=[], values={}, image_path=lambda _: None
    ).graph


def test_background_swap_in_the_graph(tmp_path: Path) -> None:
    g = _graph(tmp_path, bg="neon_purple")
    assert "alphamerge" in g and "[mt0]crop=" in g  # streamer cut out with the matte
    assert list(tmp_path.glob("cam_bg_neon_purple_*.png"))
    blur = _graph(tmp_path, bg="blur_soft")
    assert "[cb0]boxblur=" in blur and "alphamerge" in blur  # their own room, blurred
    assert "alphamerge" not in _graph(tmp_path, bg="original")
    assert "alphamerge" not in _graph(tmp_path, bg="sunset", matte_file=False)  # no cut-out
    assert "alphamerge" not in _graph(tmp_path, bg="sunset", kind="action")  # no person


def test_facecam_is_cleaned_and_sharpened_when_enlarged(tmp_path: Path) -> None:
    g = _graph(tmp_path, bg="original")
    assert "hqdn3d" in g and "flags=lanczos" in g and "unsharp=5:5" in g
    plain = _graph(tmp_path, bg="original", cam_enhance=False)
    assert "hqdn3d" not in plain and "lanczos" not in plain


def test_hdr_is_the_default_grade(tmp_path: Path) -> None:
    assert sc.Effects().color == "hdr"
    assert "saturation=1.3" in _graph(tmp_path, bg="original")
    assert "saturation=1.3" not in _graph(tmp_path, bg="original", color="vivid")


def test_every_picture_background_draws_at_any_size() -> None:
    pics = [b for b in sc.CAM_BACKGROUNDS if b != "original" and b not in sc.BLUR_BACKGROUNDS]
    assert len(pics) == 8 and len(sc.CAM_BACKGROUNDS) == 11
    for b in pics:
        img = raster.cam_background(b, 300, 200)
        assert img.size == (300, 200) and img.mode == "RGB"
        assert np.asarray(img).std() > 3  # not a flat colour
    with pytest.raises(ValueError):
        raster.cam_background("nope", 10, 10)


def test_background_pictures_and_list_are_served(client: TestClient) -> None:
    r = client.get("/api/v1/render/backgrounds/sunset.png?w=120&h=90")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert client.get("/api/v1/render/backgrounds/blur_soft.png").status_code == 404
    assert client.get("/api/v1/render/backgrounds/nope.png").status_code == 404
    opts = client.get("/api/v1/render/options").json()
    assert [b["id"] for b in opts["cam_backgrounds"]][:3] == [
        "original",
        "blur_soft",
        "blur_strong",
    ]


@needs_ffmpeg
def test_matte_video_marks_the_person(tmp_path: Path) -> None:
    src = tmp_path / "clip.mp4"
    subprocess.run(
        [ffmpeg._exe("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
         "testsrc2=size=640x360:rate=30:duration=2", "-pix_fmt", "yuv420p", str(src)],
        check=True,
    )  # fmt: skip
    out = tmp_path / "matte.mp4"
    cam = Box(0.5, 0.2, 0.3, 0.5)
    w, h = matte.build_matte(
        src, [cam], out, src_w=640, src_h=360, duration=2.0, make_segmenter=FakeSegmenter
    )
    assert (w, h) == (640, 360)
    info = ffmpeg.probe(out)
    assert info.duration_s is not None and abs(info.duration_s - 2.0) < 0.2
    frame = subprocess.run(
        [ffmpeg._exe("ffmpeg"), "-v", "error", "-ss", "1", "-i", str(out), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    m = np.frombuffer(frame, np.uint8).reshape(h, w)
    (r,) = matte.regions_for([cam], w, h)
    assert m[r.y + r.h // 2, r.x + r.w // 4] > 200  # person
    assert m[r.y + r.h // 2, r.x + r.w * 3 // 4] < 40  # background
    assert m[10, 10] < 10  # outside every facecam


def test_matte_crop_follows_the_cam_crop() -> None:
    assert matte.matte_crop((960, 540, 480, 270), 1920, 1080, 1280, 720) == (640, 360, 320, 180)
    x, y, w, h = matte.matte_crop((1900, 1070, 400, 300), 1920, 1080, 1280, 720)
    assert x + w <= 1280 and y + h <= 720 and w % 2 == 0 and h % 2 == 0


@needs_ffmpeg
def test_render_with_a_swapped_background(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        reframe,
        "find_people",
        lambda samples: reframe.People("overlay", [Box(0.6, 0.05, 0.3, 0.4)]),
    )
    model = tmp_path / "seg.tflite"
    model.write_bytes(b"x")
    monkeypatch.setattr(vision_sig, "ensure_segment_model", lambda _d: model)
    monkeypatch.setattr(matte, "MediaPipeSegmenter", lambda _m: FakeSegmenter())
    sid = seed_short(video_s=16, start=3, end=12)
    short = render(client, sid, template="streamer_first")
    assert short["status"] == "review", short["versions"][0]["qc_reasons"]
    studio = client.get(f"/api/v1/shorts/{sid}/studio").json()
    cut = studio["cut"]
    assert cut["matte_asset_id"] and cut["matte_w"] > 0
    assert studio["scene"]["regions"]["cam_bg"] == "blur_soft"  # the default
    assert client.get(f"/api/v1/media/{cut['matte_asset_id']}").status_code == 200
    scene = studio["scene"]
    scene["regions"]["cam_bg"] = "aurora"
    r = client.post(f"/api/v1/shorts/{sid}/render", json={"scene": scene})
    assert r.status_code == 202
    run_jobs()
    after = client.get(f"/api/v1/shorts/{sid}").json()
    assert after["status"] == "review" and after["active"]["version_no"] == 2
    assert media_path(after["active"]["mp4_asset_id"]).exists()
    again = client.get(f"/api/v1/shorts/{sid}/studio").json()
    assert again["cut"]["key"] == cut["key"]  # new background, same cut and matte
    assert len(list(cuts.cuts_root(uuid.UUID(sid)).iterdir())) == 1
