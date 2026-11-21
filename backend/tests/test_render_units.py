from __future__ import annotations

import re
from itertools import pairwise

import pytest

from clipforge.pipeline.render import captions, compose, reframe
from clipforge.pipeline.render.edl import CaptionWord, build_edl, caption_words
from clipforge.pipeline.render.effects import audio_chain, pick_peaks, zoom_expression
from clipforge.pipeline.render.reframe import Analysis, Box, Sample
from clipforge.pipeline.transcription.sentences import Word


def wd(s: float, e: float, t: str) -> Word:
    return Word(s, e, " " + t)


WORDS = [
    wd(10.0, 10.4, "The"),
    wd(10.4, 10.8, "car"),
    wd(10.9, 11.3, "is"),
    wd(11.3, 11.8, "fast."),
    wd(13.5, 13.8, "um"),
    wd(15.0, 15.4, "It"),
    wd(15.4, 16.0, "crashed!"),
]


# ------------------------------------------------------------------ EDL
def test_edl_cuts_dead_air_and_fillers() -> None:
    edl = build_edl(WORDS, 10.0, 16.0)
    assert len(edl.spans) == 2  # the 3.7 s pause (with a lone "um") is removed
    assert edl.spans[0].start == pytest.approx(9.85)
    assert edl.spans[1].end == pytest.approx(16.45)
    assert edl.duration < 4.5
    assert edl.map(10.4) == pytest.approx(0.55)
    assert edl.map(13.6) is None  # inside the cut
    assert edl.map_clamped(13.6) == pytest.approx(edl.spans[0].duration)


def test_edl_keeps_natural_pauses() -> None:
    edl = build_edl([wd(0, 1, "a"), wd(1.4, 2, "b"), wd(2.4, 3, "c")], 0, 3)
    assert len(edl.spans) == 1  # 0.4 s pauses are speech rhythm, not dead air


def test_caption_words_follow_the_edit() -> None:
    edl = build_edl(WORDS, 10.0, 16.0)
    cw = caption_words(WORDS, edl)
    assert [w.text for w in cw] == ["The", "car", "is", "fast.", "It", "crashed!"]
    assert all(b.start >= a.start for a, b in pairwise(cw))
    assert cw[4].start == pytest.approx(edl.spans[0].duration + 0.1, abs=0.01)


# ------------------------------------------------------------------ captions
CW = [
    CaptionWord(0.0, 0.4, "The"),
    CaptionWord(0.4, 0.8, "bridge"),
    CaptionWord(0.8, 1.2, "jump."),
    CaptionWord(2.0, 2.4, "No"),
    CaptionWord(2.4, 2.8, "way!"),
]


def dialogues(ass: str) -> list[str]:
    return [line for line in ass.splitlines() if line.startswith("Dialogue:")]


@pytest.mark.parametrize("style", list(captions.STYLES))
def test_every_style_produces_valid_ass(style: str) -> None:
    ass = captions.build_ass(CW, style=style, keywords=["bridge"], hook="big jump", duration=3.0)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    lines = dialogues(ass)
    assert lines[0].startswith("Dialogue: 1,0:00:00.00,0:00:03.00,Hook") and lines[0].endswith(
        "BIG JUMP"
    )
    caps = [line for line in lines if ",Cap," in line]
    assert caps
    assert captions.coverage(CW, ass) == 1.0


def test_highlight_and_keyword_colours() -> None:
    ass = captions.build_ass(CW, style="classic", keywords=["BRIDGE"])
    caps = [line for line in dialogues(ass) if ",Cap," in line]
    assert len(caps) == 5  # one event per spoken word
    yellow, green = captions.ass_color("#FFE135"), captions.ass_color("#3DDC84")
    first = caps[0]
    assert f"{{\\c{yellow}}}THE" in first and f"{{\\c{green}}}BRIDGE" in first
    assert "{\\c" + yellow + "}BRIDGE" in caps[1]  # spoken word wins over keyword colour


def test_groups_break_on_sentence_end_and_gaps() -> None:
    groups = captions.group_words(CW, 3)
    assert [[w.text for w in g.words] for g in groups] == [
        ["The", "bridge", "jump."],
        ["No", "way!"],
    ]
    assert groups[0].end == pytest.approx(1.8)  # min(next start, last end + 0.6)


def test_ass_text_is_sanitised_and_sized() -> None:
    ass = captions.build_ass(
        [CaptionWord(0, 1, "{\\b1}hack\\N")], style="minimal", size=(1080, 1350)
    )
    assert "PlayResY: 1350" in ass and "{\\b1}" not in ass and "hackN" in ass
    assert captions.ass_color("#112233") == "&H00332211"


# ------------------------------------------------------------------ effects
def test_zoom_and_peaks() -> None:
    assert zoom_expression([]) == "1"
    z = zoom_expression([5.0])
    assert z.startswith("1+0.1*min(1,") and "clip((t-4.800)/0.2,0,1)" in z
    assert pick_peaks([0.5, 5.0, 6.0, 12.0, 19.5, 30.0], 20.0) == [5.0, 12.0]


def test_audio_chain_uses_measured_gain() -> None:
    assert "volume=6.50dB" in audio_chain({"gain_db": "6.5"})
    assert "volume=0.00dB" in audio_chain(None) and "alimiter" in audio_chain(None)


# ------------------------------------------------------------------ reframe decisions
def samples(boxes: list[list[Box]], motion: float | None = 0.5) -> list[Sample]:
    return [Sample(i * 0.25, b, motion) for i, b in enumerate(boxes)]


CAM = Box(0.80, 0.05, 0.08, 0.12)  # small face, top-right corner


def test_detect_cam_needs_a_small_steady_corner_face() -> None:
    assert reframe.detect_cam(samples([[CAM]] * 20)) is not None
    moving = [[Box(0.1 + i * 0.03, 0.3, 0.08, 0.12)] for i in range(20)]
    assert reframe.detect_cam(samples(moving)) is None
    big_centre = [[Box(0.35, 0.2, 0.3, 0.5)]] * 20
    assert reframe.detect_cam(samples(big_centre)) is None
    assert reframe.detect_cam(samples([[CAM]] * 5 + [[]] * 15)) is None  # rarely visible


def test_choose_layout() -> None:
    a = Analysis(1920, 1080, 10, samples([[CAM]] * 20), [])
    cam = reframe.detect_cam(a.samples)
    assert reframe.choose_layout(a, cam) == "stack"
    assert reframe.choose_layout(a, cam, "bubble") == "bubble"
    two = Analysis(
        1920, 1080, 10, samples([[Box(0.1, 0.3, 0.1, 0.2), Box(0.8, 0.3, 0.1, 0.2)]] * 20), []
    )
    assert reframe.choose_layout(two, None) == "full"
    alone = Analysis(1920, 1080, 10, samples([[Box(0.45, 0.3, 0.1, 0.2)]] * 20), [])
    assert reframe.choose_layout(alone, None) == "crop"
    assert reframe.choose_layout(alone, None, "stack") == "crop"  # no cam: quiet fallback


def test_track_follows_subject_holds_still_and_jumps_on_cuts() -> None:
    win = 0.316  # a 9:16 window on 16:9
    still = [[Box(0.48, 0.3, 0.1, 0.2)]] * 8  # centre ~0.53, inside the dead zone
    moved = [[Box(0.80, 0.3, 0.1, 0.2)]] * 12  # jumps right
    a = Analysis(1920, 1080, 5, samples(still + moved), cuts=[2.1])
    keys = reframe.track(a, win)
    assert keys[0][1] == pytest.approx(0.53 - win / 2, abs=0.01)
    after_cut = [x for t, x in keys if t >= 2.1]
    assert after_cut and after_cut[0] == pytest.approx(
        1 - win, abs=0.01
    )  # clamped at the right edge
    no_cut = reframe.track(Analysis(1920, 1080, 5, samples(still + moved), cuts=[]), win)
    # speed limit (keyframes are simplified, so compare speed, not step size)
    for (t0, x0), (t1, x1) in pairwise(no_cut):
        assert abs(x1 - x0) / (t1 - t0) <= 0.35 + 1e-6


def test_motion_centre_ignores_the_facecam() -> None:
    """Real-stream bug: the talking streamer's motion dragged the game crop onto the cam."""
    import numpy as np

    grid = np.zeros((reframe.GRID_H, reframe.GRID_W), dtype=np.float32)
    grid[10:18, 1:9] = 900.0  # streamer moving in a bottom-left cam
    grid[2:8, 22:28] = 600.0  # car chase on the right
    s = Sample(0.0, [], motion_x=0.4, motion=grid)
    cam = Box(0.0, 0.5, 0.3, 0.5)
    assert s.motion_centre() == 0.4  # without a cam: whole-frame centre
    centre = s.motion_centre(exclude=cam)
    assert centre is not None and 0.7 < centre < 0.85  # follows the car, not the streamer
    still = Sample(0.0, [], motion_x=None, motion=np.zeros_like(grid))
    assert still.motion_centre(exclude=cam) is None


def test_x_expression_is_piecewise_linear() -> None:
    expr = reframe.x_expression([(0.0, 0.1), (2.0, 0.5)], 1920)
    assert expr == "if(lt(t,2.000),192.0+(768.0)*(t-0.000)/2.000,960.0)"
    assert reframe.x_expression([(0.0, 0.25)], 1000) == "250.0"


# ------------------------------------------------------------------ graph
def test_video_graph_per_layout() -> None:
    base = compose.Plan("crop", 1920, 1080, 10.0, [(0.0, 0.4)], None, [5.0])
    g = compose.video_graph(base, "captions.ass")
    assert "crop=606:1080:" in g and "scale=1080:1920" in g
    assert "eval=frame" in g and "subtitles=filename=captions.ass" in g
    stack = compose.Plan("stack", 1920, 1080, 10.0, [(0.0, 0.4)], CAM.expand(2.6, 2.2))
    gs = compose.video_graph(stack, None)
    assert "vstack" in gs and f"scale=1080:{stack.top_h}" in gs and "subtitles" not in gs
    assert 538 <= stack.top_h <= 806
    full = compose.video_graph(compose.Plan("full", 1920, 1080, 10.0), None)
    assert "boxblur" in full and "overlay=(W-w)/2:(H-h)/2" in full
    bubble = compose.video_graph(
        compose.Plan("bubble", 1920, 1080, 10.0, cam=CAM.expand(2.6, 2.2)), None
    )
    assert "hypot(" in bubble and "overlay=(W-w)/2:140" in bubble
    assert re.search(r"\[v\]$", g)
