"""Real downloads against a live site. Off by default (CI must not depend on the internet).

Run manually:  $env:CF_TEST_NETWORK="1"; uv run pytest -m network -s
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from clipforge.core import ffmpeg
from clipforge.pipeline.ingest.downloader import Downloader
from clipforge.pipeline.ingest.timewin import Window

from .media import needs_ffmpeg

# "Me at the zoo": 19 s, the first YouTube upload, public since 2005.
URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

pytestmark = [
    pytest.mark.network,
    needs_ffmpeg,
    pytest.mark.skipif(os.environ.get("CF_TEST_NETWORK") != "1", reason="set CF_TEST_NETWORK=1"),
]


def test_real_metadata() -> None:
    info = Downloader().fetch_info(URL)
    assert info.id == "jNQXAC9IVRw" and info.platform == "youtube"
    assert info.duration_s and 15 < info.duration_s < 25
    assert info.title and info.channel


def test_real_audio_window_download(tmp_path: Path) -> None:
    path = Downloader().download_audio(URL, tmp_path, Window(5, 12))
    p = ffmpeg.probe(path)
    assert path.suffix == ".m4a" and p.has_audio and not p.has_video
    # exactly the window (7 s): a longer file would mean the cut started early
    assert p.duration_s is not None and 6.5 <= p.duration_s <= 7.5


def test_real_segment_download(tmp_path: Path) -> None:
    path = Downloader().download_section(URL, tmp_path, 2, 8, max_height=360)
    p = ffmpeg.probe(path)
    assert p.has_video and p.has_audio and p.duration_s is not None and 5 <= p.duration_s <= 7.5
