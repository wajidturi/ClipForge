"""Output quality: true 1080 px wide Shorts from 1440p/4K moments, 1080p editor preview."""

from __future__ import annotations

from pathlib import Path

from clipforge.core import ffmpeg
from clipforge.core.config import Settings
from clipforge.pipeline.render import compose
from clipforge.pipeline.render.edl import build_edl
from clipforge.pipeline.transcription.sentences import Word

from .media import make_video, needs_ffmpeg

WORDS = [Word(0.1, 0.8, " hello"), Word(0.9, 1.8, " there")]


def size(p: Path) -> tuple[int | None, int | None]:
    v = ffmpeg.probe(p).video
    assert v is not None
    return v.width, v.height


def test_moments_are_fetched_up_to_4k() -> None:
    assert Settings().segment_max_height == 2160


@needs_ffmpeg
def test_4k_moment_is_scaled_to_a_full_1080_crop(tmp_path: Path) -> None:
    src = make_video(tmp_path / "uhd.mp4", 2, size="3840x2160")
    out = tmp_path / "edited.mkv"
    compose.edit_pass(src, 0.0, build_edl(WORDS, 0.0, 2.0), out)
    w, h = size(out)
    assert h == 1920 and w is not None and w * 9 // 16 >= 1080  # the 9:16 crop is 1080 wide


@needs_ffmpeg
def test_small_moment_is_not_upscaled(tmp_path: Path) -> None:
    src = make_video(tmp_path / "sd.mp4", 2)
    out = tmp_path / "edited.mkv"
    compose.edit_pass(src, 0.0, build_edl(WORDS, 0.0, 2.0), out)
    assert size(out) == (640, 360)
