"""Video size: 5 presets (portrait and landscape) and any custom width x height."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from clipforge.core import ffmpeg
from clipforge.pipeline.render import raster, reframe
from clipforge.pipeline.render import scene as sc
from clipforge.pipeline.render.reframe import Box
from clipforge.pipeline.render.scene_render import CutPlan, build_graph

from .media import needs_ffmpeg
from .test_render_flow import client, media_path, offline_faces, render, run_jobs, seed_short

__all__ = ["client", "offline_faces"]
CTX = sc.Ctx(10.0, [3.0])


def scene_at(template: str, **canvas: object) -> sc.Scene:
    s = sc.default_scene(template, CTX)
    s.canvas = sc.Canvas.model_validate(canvas)
    return s


# ------------------------------------------------------------------ the setting
def test_presets_set_the_size_and_custom_takes_any_size() -> None:
    assert (sc.Canvas().w, sc.Canvas().h) == (1080, 1920)
    wide = sc.Canvas(preset="16:9", w=500, h=500)  # a preset ignores sent numbers
    assert (wide.w, wide.h) == (1920, 1080)
    assert len(sc.CANVAS_PRESETS) == 5
    assert {k for k, (w, h, _) in sc.CANVAS_PRESETS.items() if w > h} == {"16:9", "4:3"}
    c = sc.Canvas(preset="custom", w=1001, h=777)
    assert (c.w, c.h) == (1000, 776)  # even sizes for the encoder
    with pytest.raises(ValueError, match="4x"):
        sc.Canvas(preset="custom", w=3000, h=500)
    with pytest.raises(ValueError):
        sc.Canvas(preset="custom", w=100, h=500)  # below the minimum


def test_design_canvas_keeps_a_1080_short_side() -> None:
    assert sc.design_size(scene_at("cinematic")) == (1080, 1920)
    assert sc.design_size(scene_at("cinematic", preset="16:9")) == (1920, 1080)
    assert sc.design_size(scene_at("cinematic", preset="4:5")) == (1080, 1350)
    assert sc.design_size(scene_at("cinematic", preset="custom", w=720, h=1280)) == (1080, 1920)


# ------------------------------------------------------------------ geometry
@pytest.mark.parametrize("preset", ["9:16", "4:5", "1:1", "16:9", "4:3"])
@pytest.mark.parametrize("template", sc.TEMPLATE_IDS)
def test_panels_stay_inside_every_canvas(preset: str, template: str) -> None:
    s = scene_at(template, preset=preset)
    w, h = sc.design_size(s)
    for r in sc.panels(s).values():
        assert r.x >= 0 and r.y >= 0 and r.x + r.w <= w + 1 and r.y + r.h <= h + 1
    img = raster.frame_image(s)
    assert img is None or img.size == (w, h)


def test_landscape_puts_stacked_panels_side_by_side() -> None:
    p = sc.panels(scene_at("streamer_first", preset="16:9"))
    assert p["cam"].x < p["game"].x and p["cam"].y == p["game"].y
    g = sc.panels(scene_at("gameplay_first", preset="16:9"))
    assert g["game"].x < g["cam"].x  # gameplay on the left
    portrait = sc.panels(scene_at("streamer_first"))
    assert portrait["cam"].y < portrait["game"].y


def test_several_streamers_stack_in_a_tall_panel() -> None:
    tiles = sc.cam_tiles(sc.Rect(14, 14, 600, 1000), 2)
    assert tiles[0].x == tiles[1].x and tiles[1].y > tiles[0].y
    assert tiles[1].y + tiles[1].h == 1014


def test_landscape_divider_is_vertical() -> None:
    pts = raster.divider_points(scene_at("dual_vision", preset="16:9"))
    ys = sorted(y for _, y in pts)
    assert ys[0] < 0 and ys[-1] > 1080  # crosses from top to bottom


# ------------------------------------------------------------------ the graph
def _graph(s: sc.Scene, tmp: Path) -> str:
    plan = CutPlan(1920, 1080, 10.0, None, [(0.0, 0.5)], [], [3.0])
    return build_graph(s, plan, tmp, words=[], keywords=[], values={"hook": "HI"},
                       image_path=lambda _: None).graph  # fmt: skip


def test_graph_draws_at_the_design_size_and_scales_to_the_canvas(tmp_path: Path) -> None:
    portrait = _graph(scene_at("streamer_first"), tmp_path)
    assert "s=1080x1920" in portrait and "flags=lanczos,setsar=1,format" not in portrait
    wide = _graph(scene_at("streamer_first", preset="16:9"), tmp_path)
    assert "s=1920x1080" in wide
    custom = _graph(scene_at("cinematic", preset="custom", w=720, h=1280), tmp_path)
    assert "scale=720:1280:flags=lanczos" in custom


# ------------------------------------------------------------------ real renders
@needs_ffmpeg
@pytest.mark.parametrize(
    ("canvas", "size"),
    [({"preset": "16:9"}, (1920, 1080)), ({"preset": "custom", "w": 720, "h": 900}, (720, 900))],
)
def test_render_at_a_chosen_size(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    canvas: dict[str, object],
    size: tuple[int, int],
) -> None:
    monkeypatch.setattr(
        reframe,
        "find_people",
        lambda samples: reframe.People("overlay", [Box(0.7, 0.05, 0.25, 0.3)]),
    )
    sid = seed_short(video_s=16, start=3, end=12)
    short = render(client, sid, template="streamer_first", canvas=canvas)
    assert short["status"] == "review", short["versions"][0]["qc_reasons"]
    info = ffmpeg.probe(media_path(short["active"]["mp4_asset_id"]))
    assert info.video is not None and (info.video.width, info.video.height) == size
    with Image.open(media_path(short["active"]["cover_asset_id"])) as cover:
        assert cover.size == size
    studio = client.get(f"/api/v1/shorts/{sid}/studio").json()
    assert (studio["scene"]["canvas"]["w"], studio["scene"]["canvas"]["h"]) == size
    # a plain re-render keeps the size; a new size can be sent with the scene
    scene = studio["scene"]
    scene["canvas"] = {"preset": "1:1"}
    assert client.post(f"/api/v1/shorts/{sid}/render", json={"scene": scene}).status_code == 202
    run_jobs()
    after = client.get(f"/api/v1/shorts/{sid}").json()
    sq = ffmpeg.probe(media_path(after["active"]["mp4_asset_id"]))
    assert sq.video is not None and (sq.video.width, sq.video.height) == (1080, 1080)


def test_bad_size_is_refused(client: TestClient) -> None:
    sid = seed_short()
    r = client.post(
        f"/api/v1/shorts/{sid}/render", json={"canvas": {"preset": "custom", "w": 4000, "h": 200}}
    )
    assert r.status_code == 422


def test_size_presets_are_listed(client: TestClient) -> None:
    o = client.get("/api/v1/render/options").json()
    assert [c["id"] for c in o["canvases"]] == ["9:16", "4:5", "1:1", "16:9", "4:3"]
    assert o["canvas_limits"] == {"min": 240.0, "max": 3840.0, "ratio": 4.0}


# ------------------------------------------------------------------ crop & zoom
def test_a_framed_panel_shows_the_chosen_part_of_the_source() -> None:
    """Like a profile picture: the crop keeps the panel's shape, the zoom divides the
    template's crop size, the centre follows the view and never leaves the source."""
    v = sc.View(x=0.25, y=0.5, zoom=2.0)
    assert sc.view_crop(1000, 500, v, 1920, 1080) == (230, 415, 500, 250)
    # pushed back inside at the edges
    assert sc.view_crop(1000, 500, sc.View(x=0.0, y=1.0, zoom=1.0), 1920, 1080) == (
        0,
        580,
        1000,
        500,
    )
    # zooming out stops at the whole source, still the panel's shape
    x, _y, w, h = sc.view_crop(1000, 500, sc.View(zoom=0.25), 1920, 1080)
    assert (w, h) == (1920, 960) and x == 0
    # the gameplay never zooms out past the template's (full-height) crop
    assert sc.view_crop(608, 1080, sc.View(zoom=0.5), 1920, 1080, min_zoom=1.0)[2:] == (608, 1080)


def test_views_reach_the_render_graph(tmp_path: Path) -> None:
    s = scene_at("streamer_first")
    plan = CutPlan(
        1920, 1080, 10.0, Box(0.7, 0.05, 0.2, 0.3), [(0.0, 0.5)], [], [],
        cams=[Box(0.7, 0.05, 0.2, 0.3)],
    )  # fmt: skip

    def graph() -> str:
        return build_graph(
            s, plan, tmp_path, words=[], keywords=[], values={}, image_path=lambda _: None
        ).graph

    auto = graph()
    assert ":'" in auto  # the tracked gameplay crop (an x expression)
    s.regions.views = {
        "game": sc.View(x=0.2, y=0.5, zoom=1.5),
        "cam0": sc.View(x=0.8, y=0.2, zoom=2),
    }
    framed = graph()
    game = next(line for line in framed.split(";") if "[game]" in line and "crop=" in line)
    assert "'" not in game  # a fixed crop, no tracking expression
    p = sc.panels(s)
    assert p == sc.panels(scene_at("streamer_first"))  # the frames never move
    # the old free-layout field is ignored if a saved scene still has it
    old = sc.Scene.model_validate(
        {**s.model_dump(), "regions": {**s.regions.model_dump(), "place": {"game": {"x": 0.3}}}}
    )
    assert sc.panels(old) == p
