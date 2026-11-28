"""Deep mode's action-scene finder."""

from __future__ import annotations

import numpy as np

from clipforge.pipeline.selection.scenes import Activity, activity_from_curves, find_scenes


def act(busy: list[tuple[int, int]], n: int = 600, offset: float = 0.0) -> Activity:
    m = np.full(n, 0.02, dtype=np.float32)
    for a, b in busy:
        m[a:b] = 0.2
    return Activity(offset, m, np.zeros(n, dtype=np.float32))


def test_a_long_chase_stays_one_scene() -> None:
    (sc,) = find_scenes(act([(100, 280)]))
    assert sc.start <= 100 and sc.end >= 280 and sc.duration < 200


def test_short_lulls_do_not_split_a_scene() -> None:
    (sc,) = find_scenes(act([(100, 140), (143, 180)]))
    assert sc.start <= 100 and sc.end >= 180


def test_boundaries_snap_to_cuts_and_respect_used_ranges() -> None:
    a = act([(100, 140), (300, 330)])
    scenes = find_scenes(a, cuts=[95.5, 142.0], exclude=[(295.0, 335.0)])
    assert [(s.start, s.end) for s in scenes] == [(95.5, 142.0)]


def test_offsets_windows_and_spikes() -> None:
    a = act([(50, 90), (200, 240)], n=300, offset=1000.0)
    scenes = find_scenes(a, window=(1150.0, None), spikes=[(1210.0, 1212.0, "impact")])
    assert len(scenes) == 1 and scenes[0].start >= 1150 and scenes[0].kinds == ["impact"]


def test_very_long_action_is_split() -> None:
    scenes = find_scenes(act([(0, 1500)], n=1600), max_len=600)
    assert len(scenes) >= 3 and all(s.duration <= 610 for s in scenes)


def test_curves_without_motion_give_nothing() -> None:
    assert activity_from_curves({"loud": [0.1] * 50}) is None
    a = activity_from_curves(
        {"motion": [0.1] * 40, "motion_offset_s": 5, "loud": [1.0] * 20, "hop_s": 2.0}
    )
    assert a is not None and a.offset == 5 and a.loud.max() == 1.0
