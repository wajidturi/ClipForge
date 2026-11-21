from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np
import pytest

from clipforge.pipeline.signals import Spike, binned_max, merge_runs, text_cues
from clipforge.pipeline.signals import audio as audio_sig
from clipforge.pipeline.signals import banners as banner_sig
from clipforge.pipeline.signals import chat as chat_sig
from clipforge.pipeline.signals import clips as clip_sig
from clipforge.pipeline.signals import heat as heat_sig
from clipforge.pipeline.signals import replay as replay_sig
from clipforge.pipeline.signals import vision as vision_sig
from clipforge.pipeline.transcription.sentences import Sentence, Word, build_sentences

from .media import make_audio, needs_ffmpeg


# ------------------------------------------------------------------ sentences
def w(s: float, e: float, t: str) -> Word:
    return Word(s, e, t)


def test_sentences_split_on_punctuation_and_pauses() -> None:
    words = [
        w(0, 0.3, " Hello"),
        w(0.3, 0.6, " there."),
        w(0.7, 1.0, " How"),
        w(1.0, 1.2, " are"),
        w(1.2, 1.5, " you"),
        w(3.0, 3.4, " Fine"),
        w(3.4, 3.8, " thanks"),
    ]
    out = build_sentences(words)
    assert [s.text for s in out] == ["Hello there.", "How are you", "Fine thanks"]
    assert (out[1].start, out[1].end, out[1].first_word, out[1].last_word) == (0.7, 1.5, 2, 4)


def test_sentences_cap_run_on_speech() -> None:
    words = [w(i * 0.2, i * 0.2 + 0.19, " word") for i in range(50)]
    out = build_sentences(words, max_words=20)
    assert [s.last_word - s.first_word + 1 for s in out] == [20, 20, 10]
    assert build_sentences([]) == []


def test_timeline_resample_has_no_comb_on_short_sources() -> None:
    """3 samples drawn into 60 bins: the in-between bins interpolate instead of 0."""
    from clipforge.services.timeline import _resample

    out = _resample([0.2, 1.0, 0.2], hop=2.0, offset=0.0, start=0.0, end=6.0, bins=60)
    inner = out[10:50]  # between the first and last sample centres (1 s .. 5 s)
    assert min(inner) >= 0.2 and max(out) == 1.0
    # long sources: bins coarser than samples keep each bin's peak
    long = _resample([0.0] * 50 + [1.0] + [0.0] * 49, 1.0, 0.0, 0.0, 100.0, 10)
    assert long[5] == 1.0 and sum(long) == 1.0


def test_merge_runs_and_binned_max() -> None:
    assert merge_runs([False, True, True, False, True], 0.5, 10) == [(10.5, 11.5), (12.0, 12.5)]
    assert merge_runs([True, True, False], 1.0, 0, min_len=3) == []
    assert binned_max([1, 5, 2, 8], 2) == [5.0, 8.0]
    assert binned_max([], 4) == []


# ------------------------------------------------------------------ loudness
def test_loud_spike_found_at_the_right_time() -> None:
    sr = 16000
    t = np.arange(60 * sr) / sr
    x = (0.02 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    burst = (t >= 30) & (t < 33)
    x[burst] = (0.6 * np.sin(2 * np.pi * 220 * t[burst])).astype(np.float32)
    db = audio_sig.loudness_db(x, sr, 0.5)
    spikes = audio_sig.loud_spikes(db, hop_s=0.5, offset_s=100.0)
    assert len(spikes) == 1
    sp = spikes[0]
    assert 129.5 <= sp.start <= 130.5 and 132.5 <= sp.end <= 133.5  # offset applied
    assert sp.meta["rise_db"] > 20 and sp.score > 0.9 and sp.label.startswith("+")


def test_steady_loud_audio_is_not_a_spike() -> None:
    x = (0.5 * np.sin(np.arange(30 * 16000) / 16000 * 2 * np.pi * 300)).astype(np.float32)
    assert audio_sig.loud_spikes(audio_sig.loudness_db(x)) == []


@needs_ffmpeg
def test_decode_pcm_real_file(tmp_path: Path) -> None:
    x = audio_sig.decode_pcm(make_audio(tmp_path / "a.m4a", 3))
    assert 2.9 * 16000 <= len(x) <= 3.1 * 16000 and np.abs(x).max() > 0.1


# ------------------------------------------------------------------ text cues
def sent(text: str, s: float = 0) -> Sentence:
    return Sentence(s, s + 2, text, 0, 0)


@pytest.mark.parametrize(
    ("text", "type_", "label"),
    [
        ("Ha ha ha!", "laugh", "laughter"),
        ("hahaha that's crazy", "laugh", "laughter"),
        ("(laughs) okay", "laugh", "laughter"),
        ("No way he did that", "moment", "reaction words"),
        ("Let's gooo", "moment", "reaction words"),
        ("NOOOO", "moment", "shouting"),
    ],
)
def test_text_cues(text: str, type_: str, label: str) -> None:
    [sp] = text_cues.text_spikes([sent(text)])
    assert (sp.type, sp.label) == (type_, label)


def test_text_cues_ignore_normal_speech() -> None:
    assert text_cues.text_spikes([sent("We drive to the airport now."), sent("Hold on.")]) == []


# ------------------------------------------------------------------ chat
def yt_line(ms: int, text: str, author: str = "viewer", emoji: bool = False) -> str:
    runs: list[dict[str, Any]] = [{"text": text}]
    if emoji:
        runs.append({"emoji": {"shortcuts": [":fire:"]}})
    return json.dumps(
        {
            "replayChatItemAction": {
                "videoOffsetTimeMsec": str(ms),
                "actions": [
                    {
                        "addChatItemAction": {
                            "item": {
                                "liveChatTextMessageRenderer": {
                                    "message": {"runs": runs},
                                    "authorName": {"simpleText": author},
                                }
                            }
                        }
                    }
                ],
            }
        }
    )


def test_parse_youtube_live_chat(tmp_path: Path) -> None:
    p = tmp_path / "chat.live_chat.json"
    lines = [yt_line(1500, "W ", emoji=True), "not json", yt_line(3000, "LOL ", emoji=True)]
    p.write_text("\n".join(lines), encoding="utf-8")
    msgs = chat_sig.parse_chat_file(p)
    assert [(m.t, m.text) for m in msgs] == [(1.5, "W :fire:"), (3.0, "LOL :fire:")]


def test_emote_shortcuts_are_single_tokens() -> None:
    msgs = [chat_sig.ChatMessage(0, "a", "so :fire: good"), chat_sig.ChatMessage(1, "b", ":fire:")]
    assert chat_sig.top_phrases(msgs) == [":FIRE:"]


def test_parse_twitch_rechat_both_shapes(tmp_path: Path) -> None:
    v5 = tmp_path / "a.rechat.json"
    v5.write_text(
        json.dumps(
            {
                "comments": [
                    {
                        "content_offset_seconds": 12.5,
                        "commenter": {"display_name": "bob"},
                        "message": {"body": "KEKW"},
                    }
                ]
            }
        )
    )
    gql = tmp_path / "b.rechat.json"
    gql.write_text(
        json.dumps(
            [
                {
                    "node": {
                        "contentOffsetSeconds": 7,
                        "commenter": {"displayName": "amy"},
                        "message": {"fragments": [{"text": "Pog"}, {"text": "gers"}]},
                    }
                }
            ]
        )
    )
    assert [(m.t, m.author, m.text) for m in chat_sig.parse_chat_file(v5)] == [
        (12.5, "bob", "KEKW")
    ]
    assert [(m.t, m.author, m.text) for m in chat_sig.parse_chat_file(gql)] == [
        (7.0, "amy", "Poggers")
    ]


def test_chat_spike_detected_early_and_spam_ignored() -> None:
    msgs = [chat_sig.ChatMessage(float(t), f"u{t}", "hello") for t in range(0, 600, 4)]  # 15/min
    msgs += [chat_sig.ChatMessage(300 + i * 0.15, f"x{i}", "KEKW KEKW") for i in range(60)]
    msgs += [chat_sig.ChatMessage(450 + i * 0.1, "Nightbot", "!discord") for i in range(80)]
    spikes, rate = chat_sig.chat_spikes(msgs, 0, 600, min_per_min=15)
    assert len(spikes) == 1  # the bot flood at 450 s does not count
    sp = spikes[0]
    assert 290 <= sp.start <= 295  # moved earlier: chat reacts late
    assert sp.meta["top"][0] == "KEKW" and sp.meta["ratio"] >= 3
    assert len(rate) == 60


def test_quiet_chat_has_no_spikes() -> None:
    msgs = [chat_sig.ChatMessage(float(t), "a", "hi") for t in range(0, 300, 30)]
    assert chat_sig.chat_spikes(msgs, 0, 300)[0] == []


# ------------------------------------------------------------------ twitch clips
def twitch_transport(pages: list[list[dict[str, Any]]]) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "id.twitch.tv":
            ok = req.url.params.get("client_secret") == "s3cret"
            return httpx.Response(200 if ok else 400, json={"access_token": "tok"})
        assert req.headers["Authorization"] == "Bearer tok" and req.headers["Client-Id"] == "cid"
        if req.url.path.endswith("/videos"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "user_id": "42",
                            "created_at": "2026-11-20T10:00:00Z",
                            "duration": "2h0m0s",
                        }
                    ]
                },
            )
        i = int(req.url.params.get("after", "0"))
        nxt = {"cursor": str(i + 1)} if i + 1 < len(pages) else {}
        return httpx.Response(200, json={"data": pages[i], "pagination": nxt})

    return httpx.MockTransport(handler)


def test_twitch_clips_paginate_and_filter_to_this_vod() -> None:
    pages = [
        [
            {
                "video_id": "123",
                "vod_offset": 600,
                "duration": 30,
                "view_count": 9999,
                "title": "omg",
            },
            {"video_id": "999", "vod_offset": 50, "duration": 20, "view_count": 5},
        ],  # other VOD
        [
            {"video_id": "123", "vod_offset": None, "duration": 20, "view_count": 5},  # no offset
            {"video_id": "123", "vod_offset": 3000, "duration": 25, "view_count": 12},
        ],
    ]
    clips = clip_sig.vod_clips("v123", "cid", "s3cret", transport=twitch_transport(pages))
    assert [c["vod_offset"] for c in clips] == [600, 3000]
    spikes = clip_sig.clip_spikes(clips, 0, 2000)  # the 3000 s clip is outside the window
    assert len(spikes) == 1 and spikes[0].start == 600 and spikes[0].end == 630
    assert spikes[0].score == pytest.approx(1.0, abs=0.01) and "9,999 views" in spikes[0].label


def test_twitch_bad_credentials() -> None:
    with pytest.raises(clip_sig.TwitchApiError, match="credentials"):
        clip_sig.vod_clips("v1", "cid", "wrong", transport=twitch_transport([[]]))


# ------------------------------------------------------------------ replay heatmap
def test_replay_spikes_from_heatmap() -> None:
    heat = [
        {"start": i * 10, "end": i * 10 + 10, "value": v}
        for i, v in enumerate([0.1, 0.2, 0.9, 1.0, 0.3, 0.7, 0.1])
    ]
    spikes = replay_sig.replay_spikes(heat, 0, 70)
    assert [(s.start, s.end) for s in spikes] == [(20, 40), (50, 60)]
    assert spikes[0].score == 1.0
    assert replay_sig.replay_spikes([], 0, 10) == []


# ------------------------------------------------------------------ heat
def test_heat_uses_available_signals_and_rewards_agreement() -> None:
    spikes = [
        Spike("loud", 10, 12, 1.0, "+18 dB"),
        Spike("laugh", 11, 13, 0.7, "laughter"),
        Spike("chat_spike", 50, 60, 1.0, "chat x6"),
    ]
    ranges = [(10.0, 13.0), (30.0, 33.0), (52.0, 55.0)]
    # upload-like: no chat/clips/replay available
    a = heat_sig.score_ranges(ranges, spikes, {"loud", "moment", "laugh"})
    assert a[1].heat == 0 and a[1].tags == []
    expected = (0.25 * 1.0 + 0.05 * 0.7) / 0.40 * heat_sig.AGREEMENT_BONUS * 100
    assert a[0].heat == pytest.approx(expected, abs=0.2)
    assert [t["type"] for t in a[0].tags] == ["LOUD", "LAUGH"]
    # with chat available the same loud moment is worth relatively less
    b = heat_sig.score_ranges(ranges, spikes, {"loud", "moment", "laugh", "chat_spike"})
    assert b[0].heat < a[0].heat and b[2].heat > 0 and b[2].tags[0]["type"] == "CHAT"


def test_heat_ignores_cut_markers() -> None:
    [s] = heat_sig.score_ranges([(0.0, 5.0)], [Spike("cut", 1, 1, 0.3)], {"loud"})
    assert s.heat == 0


# ------------------------------------------------------------------ vision
def test_moment_spikes_from_series() -> None:
    motion = [0.01] * 60 + [0.2] * 6 + [0.01] * 60
    expr = [0.1] * 40 + [0.9] * 3 + [0.1] * 83
    st = vision_sig.FrameStats(offset_s=100.0, motion=motion, face=[1.0] * 126, expression=expr)
    spikes = vision_sig.moment_spikes(st)
    kinds = {s.meta["kind"]: s for s in spikes}
    assert {"action", "reaction"} <= set(kinds)
    assert kinds["action"].start == 160 and kinds["action"].end == 166
    assert kinds["reaction"].start == 140


def make_motion_video(path: Path, fps: int = 4) -> Path:
    """10 s still grey, 4 s of random noise (big motion), 10 s still grey."""
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (320, 180))
    rng = np.random.default_rng(1)
    for i in range(24 * fps):
        if 10 * fps <= i < 14 * fps:
            frame = rng.integers(0, 255, (180, 320, 3), dtype=np.uint8)
        else:
            frame = np.full((180, 320, 3), 90, dtype=np.uint8)
        vw.write(frame)
    vw.release()
    return path


def test_analyze_frames_and_cuts_on_real_video(tmp_path: Path) -> None:
    video = make_motion_video(tmp_path / "m.mp4")
    st = vision_sig.analyze_frames(video, 50.0, face_model=None)
    assert len(st.motion) == 24
    # downscaling to 160x90 averages pixels, so noise reads ~0.1 against ~0 for stills
    assert max(st.motion[:9]) < 0.01 and min(st.motion[11:13]) > 0.05
    spikes = vision_sig.moment_spikes(st)
    action = [s for s in spikes if s.meta.get("kind") == "action"]
    assert action and 59 <= action[0].start <= 61
    cuts = vision_sig.cut_spikes(video, 50.0)
    assert any(59 <= c.start <= 61 for c in cuts)
    assert len(vision_sig.series_curve(st.motion, 6)) == 6


# ------------------------------------------------------------------ banners
class FakeOCR:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, img: np.ndarray) -> tuple[list[Any] | None, Any]:
        self.calls += 1
        if float(img.std()) > 20:  # the noise frames (std ~49 after mp4 compression)
            return [[None, "MISSlON PASSED", 0.95], [None, "+$500", 0.9]], None
        return None, None


def test_banner_spikes_merge_and_skip_static_frames(tmp_path: Path) -> None:
    video = make_motion_video(tmp_path / "m.mp4")
    ocr = FakeOCR()
    found = banner_sig.banner_spikes(video, 0.0, ["MISSION PASSED", "VICTORY"], ocr=ocr)
    assert found == []  # OCR typo "MISSlON" must not match by accident
    ocr2 = FakeOCR()
    hits = banner_sig.banner_spikes(video, 0.0, ["PASSED"], ocr=ocr2)
    assert len(hits) == 1 and 9.5 <= hits[0].start <= 10.5 and hits[0].label == "PASSED"
    assert ocr2.calls < 12  # identical still frames are not re-read
