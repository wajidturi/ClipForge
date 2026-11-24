"""Templates, scenes, rasterisation, the cached cut and the customisation studio API."""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from clipforge.core.config import get_settings
from clipforge.db.models import Job, Short
from clipforge.db.session import get_sessionmaker
from clipforge.pipeline.render import raster, reframe
from clipforge.pipeline.render import scene as sc
from clipforge.pipeline.render.edl import CaptionWord
from clipforge.pipeline.render.reframe import Box
from clipforge.services import cuts

from .media import needs_ffmpeg
from .test_render_flow import client, media_path, offline_faces, render, run_jobs, seed_short
from .test_runs_flow import seed_source

__all__ = ["client", "offline_faces"]
CTX = sc.Ctx(20.0, [6.0, 12.0])


# ------------------------------------------------------------------ scene model
@pytest.mark.parametrize("template", sc.TEMPLATE_IDS)
def test_every_template_has_valid_defaults_inside_the_frame(template: str) -> None:
    scene = sc.default_scene(template, CTX)
    assert scene.template == template and scene.layers
    sc.Scene.model_validate(scene.model_dump())  # round-trips through JSON
    for r in sc.panels(scene).values():
        assert r.w > 100 and r.h > 100 and r.x >= 0 and r.y >= 0
        assert r.x + r.w <= sc.W and r.y + r.h <= sc.H
    roles = {ly.role for ly in scene.layers}
    assert "name" in roles
    for ly in scene.layers:
        assert ly.end is None or ly.end <= CTX.duration + 0.01


def test_stacked_panels_do_not_overlap_and_follow_the_split() -> None:
    s = sc.default_scene("gameplay_first", CTX)
    p = sc.panels(s)
    assert p["game"].y < p["cam"].y and p["game"].y + p["game"].h <= p["cam"].y
    s.regions.split = 0.7
    assert sc.panels(s)["game"].h > p["game"].h


def test_templates_needing_a_facecam_fall_back_to_cinematic() -> None:
    assert sc.resolve_template("dual_vision", has_cam=False)[0] == "cinematic"
    assert sc.resolve_template("auto", has_cam=True) == ("streamer_first", None)
    assert sc.resolve_template("stack", has_cam=True)[0] == "streamer_first"  # old layout
    assert sc.resolve_template("cinematic", has_cam=False) == ("cinematic", None)


def test_switching_template_keeps_user_layers_and_caption_style() -> None:
    s = sc.default_scene("streamer_first", CTX)
    s.layers.append(sc.Layer(kind="image", role="logo", asset_id="x"))
    s.layers.append(sc.Layer(text="MY TEXT", role="user"))
    s.captions.color = "#00FF00"
    new = sc.switch_template(s, "cinematic", CTX)
    assert new.template == "cinematic" and new.effects.speed_lines
    assert [ly.text for ly in new.layers if ly.role == "user"] == ["MY TEXT"]
    assert any(ly.role == "logo" for ly in new.layers)
    assert new.captions.color == "#00FF00"


def test_placeholders_and_validation() -> None:
    assert sc.fill_text("💀 {hook}", {"hook": "Big win"}) == "💀 Big win"
    assert sc.fill_text("{channel}", {}) == ""
    with pytest.raises(ValueError):
        sc.Layer(color="red")
    assert sc.Layer(font="nope").font == "impact"


def test_cover_crop_keeps_the_aspect_and_stays_inside() -> None:
    x, y, w, h = sc.cover_crop((0.8, 0.05, 0.15, 0.25), 1052 / 784, 1920, 1080)
    assert abs(w / h - 1052 / 784) < 0.02 and x + w <= 1920 and y + h <= 1080


def test_reaction_found_near_the_peak() -> None:
    words = [
        CaptionWord(0.5, 0.8, "no"),
        CaptionWord(0.8, 1.0, "way"),
        CaptionWord(5.0, 5.2, "Oh"),
        CaptionWord(5.2, 5.4, "my"),
        CaptionWord(5.4, 5.6, "god!"),
    ]
    assert cuts.find_reaction(words, near=5.1) == "OH MY GOD!"
    assert cuts.find_reaction(words, near=0.4) == "NO WAY!"
    assert cuts.find_reaction([CaptionWord(0, 1, "hello")], near=None) is None


def test_track_targets_matches_track() -> None:
    a = reframe.Analysis(
        1920,
        1080,
        4.0,
        [reframe.Sample(i * 0.25, [], 0.2 + i * 0.04) for i in range(16)],
        [],
    )
    assert reframe.track(a, 0.3) == reframe.track_targets(reframe.sample_targets(a, None), [], 0.3)


# ------------------------------------------------------------------ rasterisation
def test_text_layer_with_emoji_shape_rotation() -> None:
    ly = sc.Layer(text="💀 kill", shape="burst", shape_color="#DC2626", rotation=-8, size=80)
    img = raster.render_text_layer(ly, "💀 kill")
    plain = raster.render_text_layer(sc.Layer(text="kill", shape="none", size=80), "kill")
    assert img.width > plain.width and img.height > plain.height
    colours = {px[:3] for px in img.getdata() if px[3] > 200}
    assert (220, 38, 38) in colours  # the burst fill
    assert raster.runs("ab 💀c") == [("ab ", False), ("💀", True), ("c", False)]


def test_fixed_size_bitmap_emoji_font_is_drawn_and_scaled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Noto Color Emoji (Linux) only opens at 109 px: emoji are drawn at that size and
    scaled, instead of failing with "invalid pixel size"."""
    emoji = raster.font_path("emoji")
    if emoji is None:
        pytest.skip("no emoji font on this machine")
    real = raster.ImageFont.truetype

    def bitmap_only(font: str, size: int, *a: object, **kw: object) -> object:
        if str(font) == str(emoji) and size != raster.BITMAP_EMOJI_PX:
            raise OSError("invalid pixel size")
        return real(font, size, *a, **kw)  # type: ignore[arg-type]

    raster._font.cache_clear()
    small = sc.Layer(kind="emoji", text="💀", size=40, stroke=0, shadow=False)
    big = sc.Layer(kind="emoji", text="💀", size=160, stroke=0, shadow=False)
    expected = raster.render_text_layer(small, "💀")  # scalable font: drawn directly
    monkeypatch.setattr(raster.ImageFont, "truetype", bitmap_only)
    raster._font.cache_clear()
    try:
        a = raster.render_text_layer(small, "💀")
        b = raster.render_text_layer(big, "💀")
    finally:
        raster._font.cache_clear()
    assert abs(a.width - expected.width) <= 3 and abs(a.height - expected.height) <= 3
    assert b.width > 3 * a.width * 0.8  # scaled with the size
    assert a.getchannel("A").getextrema()[1] > 200  # the emoji is visible


def test_frame_has_holes_for_panels_and_a_cam_ring() -> None:
    s = sc.default_scene("streamer_first", CTX)
    f = raster.frame_image(s)
    assert f is not None
    p = sc.panels(s)
    g = p["game"]
    assert f.getpixel((g.x + g.w // 2, g.y + g.h // 2))[3] == 0  # see-through panel
    assert f.getpixel((sc.W // 2, p["game"].y - 4))[3] == 255  # gap between panels
    pip = sc.default_scene("floating_facecam", CTX)
    ring = raster.frame_image(pip)
    assert ring is not None
    c = sc.panels(pip)["cam"]
    assert ring.getpixel((c.x + c.w // 2, c.y + 2))[3] > 100  # ring at the top of the circle


# ------------------------------------------------------------------ studio flow
def png_bytes(color: str = "#FF0000") -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (120, 60), color).save(buf, "PNG")
    return buf.getvalue()


def test_image_library_upload_list_delete(client: TestClient) -> None:
    r = client.post("/api/v1/images", files={"file": ("logo.png", png_bytes(), "image/png")})
    assert r.status_code == 201, r.text
    img = r.json()
    assert (img["width"], img["height"]) == (120, 60)
    assert client.get(f"/api/v1/media/{img['id']}").content[:4] == b"\x89PNG"
    assert [i["id"] for i in client.get("/api/v1/images").json()] == [img["id"]]
    bad = client.post("/api/v1/images", files={"file": ("x.png", b"not an image", "image/png")})
    assert bad.status_code == 422
    assert client.delete(f"/api/v1/images/{img['id']}").status_code == 204
    assert client.get("/api/v1/images").json() == []


def test_fonts_are_served(client: TestClient) -> None:
    r = client.get("/api/v1/fonts/impact")
    assert r.status_code == 200 and len(r.content) > 10_000
    assert client.get("/api/v1/fonts/../secret").status_code == 404


@needs_ffmpeg
def test_template_render_then_studio_rerender_reuses_the_cut(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reframe, "detect_cam", lambda samples: Box(0.75, 0.05, 0.2, 0.3))
    sid = seed_short(video_s=24, start=4, end=18)
    short = render(client, sid, template="streamer_first")
    v1 = short["active"]
    assert short["status"] == "review" and v1["layout"] == "streamer_first", v1

    studio = client.get(f"/api/v1/shorts/{sid}/studio").json()
    assert studio["scene"]["template"] == "streamer_first" and studio["cut"] is not None
    cut = studio["cut"]
    assert cut["cam"] and cut["words"] and cut["targets"]
    preview = client.get(f"/api/v1/media/{cut['preview_asset_id']}")
    assert preview.status_code == 200 and len(preview.content) > 1000

    switched = client.post(
        f"/api/v1/shorts/{sid}/scene/template",
        json={"template": "dual_vision", "scene": studio["scene"]},
    ).json()
    assert switched["template"] == "dual_vision"

    logo = client.post("/api/v1/images", files={"file": ("logo.png", png_bytes(), "image/png")})
    scene = switched
    scene["layers"].append(
        {"kind": "image", "role": "logo", "asset_id": logo.json()["id"], "x": 0.85, "y": 0.06}
    )
    scene["layers"].append({"kind": "text", "role": "user", "text": "GG", "x": 0.5, "y": 0.3})
    scene["captions"]["visible"] = False
    r = client.post(f"/api/v1/shorts/{sid}/render", json={"scene": scene, "origin": "manual_edit"})
    assert r.status_code == 202, r.text
    run_jobs()
    after = client.get(f"/api/v1/shorts/{sid}").json()
    v2 = after["active"]
    assert v2["version_no"] == 2 and v2["layout"] == "dual_vision" and v2["origin"] == "manual_edit"
    assert media_path(v2["mp4_asset_id"]).exists()
    saved = client.get(f"/api/v1/shorts/{sid}/studio").json()
    assert any(ly["text"] == "GG" for ly in saved["scene"]["layers"])
    assert saved["cut"]["key"] == cut["key"]  # same range: the cut was reused
    root = cuts.cuts_root(uuid.UUID(sid))
    assert len([d for d in root.iterdir() if d.is_dir()]) == 1
    # a plain re-render keeps the customised look
    render(client, sid)
    again = client.get(f"/api/v1/shorts/{sid}/studio").json()
    assert again["scene"]["template"] == "dual_vision"
    assert any(ly["text"] == "GG" for ly in again["scene"]["layers"])


def test_one_click_run_with_whole_clips_queues_template_renders(client: TestClient) -> None:
    src = seed_source()
    r = client.post(
        "/api/v1/runs",
        json={
            "source_ids": [src],
            "pick_mode": "whole",
            "render": {"template": "cinematic", "aspects": []},
        },
    )
    assert r.status_code == 201, r.text
    from clipforge.jobs.worker import Worker

    Worker("t", caps=("cpu",)).run_once()  # picking only
    run = client.get(f"/api/v1/runs/{r.json()['id']}").json()
    assert len(run["shorts"]) == 1 and run["shorts"][0]["status"] == "rendering"
    with get_sessionmaker()() as s:
        short = s.get(Short, uuid.UUID(run["shorts"][0]["id"]))
        job = s.get(Job, uuid.UUID(run["shorts"][0]["render_job_id"]))
        assert short is not None and job is not None
        assert job.payload["options"]["template"] == "cinematic"
    part = run["shorts"][0]["parts"][0]
    assert part["end_s"] - part["start_s"] <= 180  # a 5-minute source: its best moment


def test_whole_clip_spans_all_speech_of_a_short_source() -> None:
    from clipforge.pipeline.selection import Candidate, Sent
    from clipforge.services.runs import whole_picks

    sents = {"s": [Sent("s", i, i * 5.0, i * 5.0 + 4.5, f"line {i}", 40) for i in range(9)]}
    pool = [Candidate(1, "s", 10.0, 30.0, 70, 2, 5, 20.0, head="line 2")]
    picks = whole_picks(pool, sents, {"s": "Creator"})
    assert [(p.start, p.end) for p in picks] == [(0.0, 44.5)]
    assert picks[0].reason == "whole clip" and picks[0].credit == "Creator"
    # a clip shorter than any moment window still works (no candidates at all)
    short = {"c": [Sent("c", 0, 1.0, 6.0, "Oh my god", 70), Sent("c", 1, 6.2, 17.5, "we won", 50)]}
    assert [(p.start, p.end) for p in whole_picks([], short, {"c": None})] == [(1.0, 17.5)]


def test_cam_mask_shapes() -> None:
    assert raster.cam_mask(100, "circle").getpixel((50, 50)) == 255
    assert raster.cam_mask(100, "circle").getpixel((1, 1)) == 0


@needs_ffmpeg
def test_deleting_a_source_removes_its_renders_and_cuts(client: TestClient) -> None:
    sid = seed_short(video_s=20, start=4, end=16)
    render(client, sid)
    renders = get_settings().resolved_data_dir / "renders" / sid
    assert (renders / "cuts").exists()
    with get_sessionmaker()() as s:
        short = s.get(Short, uuid.UUID(sid))
        assert short is not None
        source_id = short.source_id
    assert client.delete(f"/api/v1/sources/{source_id}").status_code == 204
    assert not renders.exists()
    assert client.get(f"/api/v1/shorts/{sid}").status_code == 404
