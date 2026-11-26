"""People on screen: several streamers with their own facecams, two people sharing one
cam, people on the main camera, who is talking, and the facecam panel when nobody
is found."""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import pytest

from clipforge.pipeline.render import reframe
from clipforge.pipeline.render import scene as sc
from clipforge.pipeline.render.reframe import Analysis, Box, Sample
from clipforge.pipeline.render.scene_render import CutPlan, build_graph
from clipforge.services import cuts

N = 40  # 10 s at 4 samples per second


def _samples(per_sample: list[list[tuple[Box, float]]]) -> list[Sample]:
    return [
        Sample(i * 0.25, [b for b, _ in faces], 0.5, None, [m for _, m in faces])
        for i, faces in enumerate(per_sample)
    ]


def talking(i: int, on: bool) -> float:
    """Mouth opening: moving while talking, still while quiet."""
    return 0.05 + 0.04 * math.sin(i * 1.7) if on else 0.02


SPEED = Box(0.08, 0.70, 0.06, 0.11)  # big cam, bottom-left
KAI = Box(0.86, 0.72, 0.045, 0.08)  # small cam, bottom-right


def test_two_streamers_with_their_own_cams_and_a_moving_game_face() -> None:
    """The Kai Cenat / Speed stream: two cam overlays plus GTA characters' faces."""
    frames = []
    for i in range(N):
        game_face = Box(0.3 + i * 0.01, 0.3, 0.05, 0.09)  # walks across the screen
        frames.append([(SPEED, talking(i, True)), (KAI, talking(i, False)), (game_face, 0.0)])
    pp = reframe.find_people(_samples(frames))
    assert pp.kind == "overlay" and len(pp.cams) == 2
    left, right = pp.cams
    assert left.x < 0.1 and right.x > 0.75  # ordered left to right, game face ignored
    assert pp.primary == 0  # Speed is the one talking
    assert reframe.detect_cam(_samples(frames)) == left


def test_two_people_in_one_cam_share_one_box() -> None:
    a, b = Box(0.78, 0.06, 0.05, 0.09), Box(0.86, 0.07, 0.05, 0.09)
    pp = reframe.find_people(_samples([[(a, 0.03), (b, 0.03)]] * N))
    assert pp.kind == "overlay" and len(pp.cams) == 1
    cam = pp.cams[0]
    assert cam.x <= a.x and cam.x + cam.w >= b.x + b.w  # both inside


def test_nobody_steady_means_no_people() -> None:
    moving = [[(Box(0.1 + i * 0.02, 0.3, 0.06, 0.1), 0.0)] for i in range(N)]
    assert reframe.find_people(_samples(moving)).kind in ("none", "camera")
    assert reframe.find_people(_samples([[]] * N)).kind == "none"
    assert reframe.find_people(_samples([[]] * 3)).kind == "none"


def test_people_on_camera_follow_whoever_talks() -> None:
    """A couch stream: two people far apart on one camera take turns talking."""
    left, right = Box(0.12, 0.3, 0.14, 0.25), Box(0.72, 0.3, 0.14, 0.25)
    frames = [[(left, talking(i, i < N // 2)), (right, talking(i, i >= N // 2))] for i in range(N)]
    s = _samples(frames)
    pp = reframe.find_people(s)
    assert pp.kind == "camera" and len(pp.cams) == 2
    targets = reframe.sample_targets(Analysis(1920, 1080, 10, s, []), pp)
    first = [x for t, x in targets if t < 4]
    last = [x for t, x in targets if t > 7]
    assert all(x == pytest.approx(left.cx) for x in first)
    assert all(x == pytest.approx(right.cx) for x in last)


def test_people_close_together_are_framed_as_a_group() -> None:
    a, b = Box(0.40, 0.3, 0.08, 0.15), Box(0.52, 0.3, 0.08, 0.15)
    s = _samples([[(a, 0.03), (b, 0.03)]] * N)
    pp = reframe.find_people(s)
    targets = reframe.sample_targets(Analysis(1920, 1080, 10, s, []), pp)
    assert all(x == pytest.approx((a.x + b.x + b.w) / 2) for _, x in targets)


def test_speaker_changes_only_when_someone_clearly_talks_more() -> None:
    p1, p2 = reframe.Person(), reframe.Person()
    for i in range(N):
        p1.add(i, Box(0.1, 0.3, 0.1, 0.2), talking(i, True))
        p2.add(i, Box(0.7, 0.3, 0.1, 0.2), talking(i, True) * 1.05)  # about the same
    who = reframe.speakers([Sample(i * 0.25) for i in range(N)], [p1, p2])
    assert len(set(who[5:])) == 1  # no flicking between two equally loud people


def test_cam_boxes_for_old_cuts_and_for_no_people() -> None:
    old = {"cam": [0.7, 0.05, 0.2, 0.3], "targets": []}
    assert cuts.cam_boxes(old) == ([Box(0.7, 0.05, 0.2, 0.3)], 0, "overlay")
    nobody = {"cam": None, "cams": [], "targets": [(0.0, 0.8), (1.0, 0.8)]}
    boxes, _, kind = cuts.cam_boxes(nobody)
    assert kind == "action" and boxes[0].cx == pytest.approx(0.775)  # close-up of the action
    assert not cuts.has_people(nobody) and cuts.has_people(old)


def test_cam_tiles_split_the_panel_evenly() -> None:
    r = sc.Rect(14, 14, 1052, 782)
    assert sc.cam_tiles(r, 1) == [r] and sc.cam_tiles(r, 0) == []
    tiles = sc.cam_tiles(r, 3)
    assert len(tiles) == 3 and tiles[0].x == 14
    assert tiles[-1].x + tiles[-1].w == r.x + r.w
    for a, b in itertools.pairwise(tiles):
        assert b.x - (a.x + a.w) == sc.TILE_GAP


def _graph(template: str, cams: list[Box], tmp: Path) -> str:
    plan = CutPlan(1920, 1080, 10.0, cams[0], [(0.0, 0.5)], [], [], cams=cams)
    scene = sc.default_scene(template, sc.Ctx(10.0, []))
    return build_graph(
        scene, plan, tmp, words=[], keywords=[], values={}, image_path=lambda _: None
    ).graph


def test_render_draws_every_streamer_in_stacked_templates(tmp_path: Path) -> None:
    g = _graph("streamer_first", [SPEED.expand(2.6, 2.2), KAI.expand(2.6, 2.2)], tmp_path)
    assert "split=3[sg][sc0][sc1]" in g and "[cam0]" in g and "[cam1]" in g
    bubble = _graph("floating_facecam", [SPEED, KAI], tmp_path)
    assert "split=2[sg][sc0]" in bubble and "[cam1]" not in bubble  # one bubble
    cine = _graph("cinematic", [SPEED, KAI], tmp_path)
    assert "split=1[sg]" in cine and "[cam0]" not in cine


def test_narrow_cam_tiles_zoom_in_instead_of_pulling_in_more() -> None:
    """Real-stream bug: Kai's tile showed the mini game view under his cam."""
    box = (0.81, 0.6, 0.116, 0.212)  # a cam on 2560x1440, about square in pixels
    _, _, w, h = sc.cover_crop(box, 0.67, 2560, 1440)
    assert h > 0.212 * 1440 * 1.4  # plain cover grows far below the cam
    _, _, w, h = sc.cover_crop(box, 0.67, 2560, 1440, sc.CAM_MAX_GROW)
    assert h <= 0.212 * 1440 * sc.CAM_MAX_GROW + 2 and abs(w / h - 0.67) < 0.02
    assert w < 0.116 * 2560  # cut the sides instead
    assert sc.cover_crop(box, 1.0, 2560, 1440, 1.3) == sc.cover_crop(box, 1.0, 2560, 1440)


def test_facecams_are_blurred_inside_the_gameplay(tmp_path: Path) -> None:
    cams = [SPEED.expand(2.6, 2.2), KAI.expand(2.6, 2.2)]
    g = _graph("streamer_first", cams, tmp_path)
    assert g.count("boxblur=") == 2 and "[sgh]" in g
    cine = _graph("cinematic", cams, tmp_path)  # no cam panel: the cam stays visible
    assert "[sgh]" not in cine
    plan = CutPlan(1920, 1080, 10.0, cams[0], [(0.0, 0.5)], [], [], cams=cams, cam_kind="camera")
    scene = sc.default_scene("streamer_first", sc.Ctx(10.0, []))
    people = build_graph(
        scene, plan, tmp_path, words=[], keywords=[], values={}, image_path=lambda _: None
    ).graph
    assert "[sgh]" not in people  # people on camera are the content: never blurred
