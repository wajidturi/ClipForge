from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yt_dlp
from yt_dlp.utils import DownloadCancelled

from clipforge.db.enums import Platform
from clipforge.pipeline.ingest import errors
from clipforge.pipeline.ingest.downloader import Downloader, parse_info
from clipforge.pipeline.ingest.resolver import (
    InvalidSourceError,
    platform_from_extractor,
    resolve_url,
)
from clipforge.pipeline.ingest.timewin import (
    InvalidTimeError,
    Window,
    default_window,
    format_time,
    make_window,
    parse_time,
    parse_window,
)

# ------------------------------------------------------------------ resolver
URLS = [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s", Platform.youtube, "dQw4w9WgXcQ"),
    ("youtube.com/watch?feature=share&v=dQw4w9WgXcQ", Platform.youtube, "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=abc", Platform.youtube, "dQw4w9WgXcQ"),
    ("https://m.youtube.com/shorts/dQw4w9WgXcQ", Platform.youtube, "dQw4w9WgXcQ"),
    ("https://www.youtube.com/live/dQw4w9WgXcQ", Platform.youtube, "dQw4w9WgXcQ"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123", Platform.youtube, "dQw4w9WgXcQ"),
    ("https://www.twitch.tv/videos/2290012345", Platform.twitch, "v2290012345"),
    (
        "https://clips.twitch.tv/FunnyClipSlug-abc_123",
        Platform.twitch,
        "clip:FunnyClipSlug-abc_123",
    ),
    ("https://www.twitch.tv/streamer/clip/SlugName", Platform.twitch, "clip:SlugName"),
    (
        "https://kick.com/someone/videos/0b6c3a3e-1d2f-4a5b-9c8d-123456789abc",
        Platform.kick,
        "0b6c3a3e-1d2f-4a5b-9c8d-123456789abc",
    ),
    (
        "https://www.tiktok.com/@user.name/video/7301234567890123456",
        Platform.tiktok,
        "7301234567890123456",
    ),
    ("https://x.com/someone/status/1858000000000000000", Platform.x, "1858000000000000000"),
    ("https://twitter.com/someone/status/1858000000000000000", Platform.x, "1858000000000000000"),
    ("https://www.instagram.com/reel/C1aBcDeFgHi/", Platform.instagram, "C1aBcDeFgHi"),
    ("https://www.facebook.com/watch/?v=1234567890", Platform.facebook, "1234567890"),
    ("https://www.facebook.com/page/videos/9876543210/", Platform.facebook, "9876543210"),
    ("https://rumble.com/v5abcde-some-title.html", Platform.rumble, "v5abcde"),
    ("https://vimeo.com/123456789", Platform.vimeo, "123456789"),
    ("https://www.reddit.com/r/gaming/comments/1abcde/some_title/", Platform.reddit, "1abcde"),
    ("https://www.dailymotion.com/video/x8abcde", Platform.dailymotion, "x8abcde"),
    ("https://dai.ly/x8abcde", Platform.dailymotion, "x8abcde"),
]


@pytest.mark.parametrize(("url", "platform", "ext_id"), URLS)
def test_resolve_known_platforms(url: str, platform: Platform, ext_id: str) -> None:
    r = resolve_url(url)
    assert (r.platform, r.external_id, r.id_is_guess) == (platform, ext_id, False)
    assert r.url.startswith("https://")


def test_all_eleven_platforms_covered() -> None:
    assert {p for _, p, _ in URLS} == {
        p for p in Platform if p not in (Platform.other, Platform.file)
    }


def test_unknown_site_gets_stable_hash_id() -> None:
    a = resolve_url("https://example.org/watch/abc")
    b = resolve_url("https://EXAMPLE.org/watch/abc#frag")
    assert a.platform == Platform.other and a.id_is_guess
    assert a.external_id == b.external_id


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "ftp://example.com/video.mp4",
        "file:///C:/Windows/system32",
        "http://localhost:8800/api",
        "http://127.0.0.1/x",
        "http://192.168.1.10/video",
        "http://[::1]/x",
        "nope",
        "http://nas/video.mp4",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/@somechannel",
        "https://www.youtube.com/@somechannel/videos",
        "https://www.twitch.tv/streamer/videos",
    ],
)
def test_resolve_rejects(bad: str) -> None:
    with pytest.raises(InvalidSourceError):
        resolve_url(bad)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("Youtube", Platform.youtube),
        ("TwitchVod", Platform.twitch),
        ("Twitter", Platform.x),
        ("KickVOD", Platform.kick),
        ("Generic", Platform.other),
        (None, Platform.other),
    ],
)
def test_platform_from_extractor(key: str | None, expected: Platform) -> None:
    assert platform_from_extractor(key, Platform.other) == expected


# ------------------------------------------------------------------ time windows
@pytest.mark.parametrize(
    ("text", "seconds"),
    [("90", 90), ("1:30", 90), ("90:00", 5400), ("1:02:03", 3723), ("0:00:05.5", 5.5), (12, 12)],
)
def test_parse_time(text: str, seconds: float) -> None:
    assert parse_time(text) == seconds


@pytest.mark.parametrize("bad", ["abc", "1:75", "1:60:00", "-5", "1::2", -1])
def test_parse_time_rejects(bad: str) -> None:
    with pytest.raises(InvalidTimeError):
        parse_time(bad)


def test_windows() -> None:
    assert make_window(None, "") is None
    assert make_window("1:00", "2:00") == Window(60, 120)
    assert make_window("1:00", None) == Window(60, None)
    assert parse_window("1:00:00-1:30:00") == Window(3600, 5400)
    assert parse_window("45:00-") == Window(2700, None)
    with pytest.raises(InvalidTimeError):
        make_window("2:00", "1:00")
    with pytest.raises(InvalidTimeError):
        make_window("0", "5")  # under 10 s
    assert Window(60, None).clamp(100) == Window(60, 100)
    assert Window(60, 500).clamp(100) == Window(60, 100)
    with pytest.raises(InvalidTimeError):
        Window(200, None).clamp(100)
    assert format_time(3723) == "1:02:03" and format_time(65) == "1:05"


def test_default_window_only_for_long_sources() -> None:
    assert default_window(3 * 3600, 4, 2) is None
    assert default_window(None, 4, 2) is None
    assert default_window(8 * 3600, 4, 2) == Window(6 * 3600, 8 * 3600)


# ------------------------------------------------------------------ error hints
@pytest.mark.parametrize(
    ("raw", "retryable", "has_hint"),
    [
        ("ERROR: [youtube] x: Sign in to confirm you're not a bot", False, True),
        ("ERROR: Private video. Sign in if you've been granted access", False, True),
        ("ERROR: HTTP Error 429: Too Many Requests", True, True),
        ("ERROR: Unsupported URL: https://example.org", False, True),
        ("urlopen error [Errno 11001] getaddrinfo failed", True, True),
        ("something nobody predicted", True, False),
    ],
)
def test_explain(raw: str, retryable: bool, has_hint: bool) -> None:
    e = errors.explain(raw)
    assert e.retryable is retryable and (e.hint is not None) is has_hint and e.message


# ------------------------------------------------------------------ yt-dlp wrapper
INFO: dict[str, Any] = {
    "id": "abc123def45",
    "extractor_key": "Youtube",
    "title": "Big moment",
    "channel": "Some Creator",
    "channel_id": "UC1",
    "duration": 3600,
    "timestamp": 1763700000,
    "live_status": "was_live",
    "webpage_url": "https://www.youtube.com/watch?v=abc123def45",
    "heatmap": [{"start_time": 0, "end_time": 36, "value": 0.4}],
    "chapters": [{"start_time": 0, "end_time": 60, "title": "Intro"}],
}


def test_parse_info() -> None:
    r = parse_info(INFO)
    assert r.platform == Platform.youtube and r.duration_s == 3600 and r.was_live
    assert not r.is_live and r.published_at is not None and r.published_at.year == 2025
    assert r.meta()["heatmap"][0]["value"] == 0.4
    assert parse_info({**INFO, "live_status": "is_live"}).is_live
    assert parse_info({**INFO, "timestamp": None, "upload_date": "20261120"}).published_at.day == 20  # type: ignore[union-attr]
    with pytest.raises(InvalidSourceError):
        parse_info({"_type": "playlist", "id": "x"})


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: records options, fires hooks, writes a file."""

    instances: list[FakeYDL] = []

    def __init__(self, opts: dict[str, Any]) -> None:
        self.opts = opts
        FakeYDL.instances.append(self)

    def __enter__(self) -> FakeYDL:
        return self

    def __exit__(self, *a: object) -> None:
        pass

    def extract_info(self, url: str, download: bool = False) -> dict[str, Any]:
        return dict(INFO)

    def sanitize_info(self, info: dict[str, Any]) -> dict[str, Any]:
        return info

    def download(self, urls: list[str]) -> int:
        for hook in self.opts.get("progress_hooks", []):
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
        out = Path(self.opts["outtmpl"]["default"].replace("%(ext)s", "m4a"))
        out.write_bytes(b"fake")
        return 0


def test_downloader_audio_options_progress_and_output(tmp_path: Path) -> None:
    FakeYDL.instances.clear()
    seen: list[tuple[float, str]] = []
    d = Downloader(cookies_browser="firefox", ydl_factory=FakeYDL)
    path = d.download_audio(
        "https://youtu.be/abc123def45",
        tmp_path,
        Window(10, 70),
        progress=lambda p, s: seen.append((p, s)),
    )
    opts = FakeYDL.instances[-1].opts
    assert path == tmp_path / "audio.m4a" and path.exists()
    assert opts["format"] == "bestaudio/best" and opts["noplaylist"] is True
    assert opts["cookiesfrombrowser"] == ("firefox",)
    assert "download_ranges" in opts
    assert opts["force_keyframes_at_cuts"] is True  # exact cut, see check_window_alignment
    assert opts["postprocessors"][0]["preferredcodec"] == "m4a"
    assert seen and seen[0][0] == 50


def test_downloader_no_window_downloads_everything(tmp_path: Path) -> None:
    FakeYDL.instances.clear()
    Downloader(ydl_factory=FakeYDL).download_audio("https://youtu.be/abc123def45", tmp_path)
    assert "download_ranges" not in FakeYDL.instances[-1].opts
    assert "cookiesfrombrowser" not in FakeYDL.instances[-1].opts


def test_downloader_cancel_stops_in_hook(tmp_path: Path) -> None:
    with pytest.raises(DownloadCancelled):
        Downloader(ydl_factory=FakeYDL).download_audio(
            "https://youtu.be/abc123def45", tmp_path, is_cancelled=lambda: True
        )


def test_downloader_section_options(tmp_path: Path) -> None:
    FakeYDL.instances.clear()
    Downloader(ydl_factory=FakeYDL).download_section("https://youtu.be/x", tmp_path, 100, 130)
    opts = FakeYDL.instances[-1].opts
    assert opts["force_keyframes_at_cuts"] and opts["merge_output_format"] == "mp4"
    assert "height<=2160" in opts["format"]  # 4K moments: sharp 9:16 crops


def test_section_downloads_cannot_hang_forever(tmp_path: Path) -> None:
    """Real bug: ffmpeg waited on a silent YouTube connection for 47 minutes."""
    FakeYDL.instances.clear()
    Downloader(ydl_factory=FakeYDL).download_section("https://youtu.be/x", tmp_path, 100, 130)
    args = FakeYDL.instances[-1].opts["external_downloader_args"]["ffmpeg_i"]
    assert args[args.index("-rw_timeout") + 1] == "30000000"  # 30 s without data -> error
    assert "-reconnect_on_network_error" in args


class FlakyYDL(FakeYDL):
    """Fails the first download like a stalled ffmpeg, then works."""

    def download(self, urls: list[str]) -> int:
        if len(FakeYDL.instances) == 1:
            raise yt_dlp.utils.DownloadError("ffmpeg exited with code 1")
        return super().download(urls)


def test_a_stalled_section_download_is_tried_again(tmp_path: Path) -> None:
    FakeYDL.instances.clear()
    seen: list[str] = []
    path = Downloader(ydl_factory=FlakyYDL).download_section(
        "https://youtu.be/x", tmp_path, 100, 130, progress=lambda p, s: seen.append(s)
    )
    assert path.exists() and len(FakeYDL.instances) == 2
    assert any("stalled" in s for s in seen)


def test_stall_guard_ends_ffmpeg_when_the_file_stops_growing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from clipforge.pipeline.ingest import downloader as dl

    killed: list[int] = []
    monkeypatch.setattr(dl._StallGuard, "_kill_ffmpeg", lambda self: killed.append(1))
    (tmp_path / "seg.mp4.part").write_bytes(b"x")
    g = dl._StallGuard(tmp_path, "seg", stall_s=0.1)
    g.start()
    import time

    time.sleep(5.5)  # the guard looks every 5 s
    g.stop()
    assert killed


def test_fetch_info(tmp_path: Path) -> None:
    info = Downloader(ydl_factory=FakeYDL).fetch_info("https://youtu.be/abc123def45")
    assert info.id == "abc123def45" and info.title == "Big moment"
