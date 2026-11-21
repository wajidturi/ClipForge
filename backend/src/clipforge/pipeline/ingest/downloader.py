"""yt-dlp wrapper: metadata, audio-only download, and short segment download.

The YoutubeDL class is injected so tests can replace the network with recorded
metadata. Progress goes to a callback; cancellation is checked in yt-dlp's
progress hook and stops the download immediately.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadCancelled, download_range_func

from clipforge.db.enums import Platform
from clipforge.pipeline.ingest.resolver import InvalidSourceError, platform_from_extractor
from clipforge.pipeline.ingest.timewin import Window

ProgressFn = Callable[[float, str], None]
CancelFn = Callable[[], bool]
YdlFactory = Callable[[dict[str, Any]], Any]


@dataclass
class RemoteInfo:
    id: str
    extractor_key: str
    platform: Platform
    title: str | None
    channel: str | None
    channel_id: str | None
    duration_s: float | None
    published_at: datetime | None
    language: str | None
    is_live: bool
    was_live: bool
    thumbnail: str | None
    webpage_url: str
    view_count: int | None
    chapters: list[dict[str, Any]] = field(default_factory=list)
    heatmap: list[dict[str, Any]] = field(default_factory=list)

    def meta(self) -> dict[str, Any]:
        """What we keep in sources.meta (chapters/heatmap feed later signal analysis)."""
        return {
            "extractor": self.extractor_key,
            "channel_id": self.channel_id,
            "thumbnail": self.thumbnail,
            "view_count": self.view_count,
            "was_live": self.was_live,
            "chapters": self.chapters,
            "heatmap": self.heatmap,
        }


class DownloadError(RuntimeError):
    pass


class _Logger:
    """Collects yt-dlp's messages instead of printing them; errors feed `explain()`."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)


def _published(info: dict[str, Any]) -> datetime | None:
    for key in ("release_timestamp", "timestamp"):
        if isinstance(info.get(key), (int, float)):
            return datetime.fromtimestamp(info[key], tz=UTC)
    if isinstance(d := info.get("upload_date"), str) and len(d) == 8 and d.isdigit():
        return datetime(int(d[:4]), int(d[4:6]), int(d[6:]), tzinfo=UTC)
    return None


def parse_info(info: dict[str, Any], fallback: Platform = Platform.other) -> RemoteInfo:
    if info.get("_type") == "playlist":
        raise InvalidSourceError("this link is a playlist; paste the link of one video")
    status = info.get("live_status")
    return RemoteInfo(
        id=str(info["id"]),
        extractor_key=str(info.get("extractor_key") or info.get("extractor") or ""),
        platform=platform_from_extractor(info.get("extractor_key"), fallback),
        title=info.get("title"),
        channel=info.get("channel") or info.get("uploader") or info.get("creator"),
        channel_id=info.get("channel_id") or info.get("uploader_id"),
        duration_s=float(info["duration"]) if info.get("duration") else None,
        published_at=_published(info),
        language=info.get("language"),
        is_live=bool(info.get("is_live")) or status in ("is_live", "is_upcoming"),
        was_live=bool(info.get("was_live")) or status == "was_live",
        thumbnail=info.get("thumbnail"),
        webpage_url=str(info.get("webpage_url") or info.get("original_url") or ""),
        view_count=info.get("view_count"),
        chapters=[
            {"start": c.get("start_time"), "end": c.get("end_time"), "title": c.get("title")}
            for c in info.get("chapters") or []
        ],
        heatmap=[
            {"start": h.get("start_time"), "end": h.get("end_time"), "value": h.get("value")}
            for h in info.get("heatmap") or []
        ],
    )


def _deno_path() -> str | None:
    """deno ships inside the venv (yt-dlp[deno]); it solves YouTube's JS challenge."""
    local = Path(sys.executable).parent / ("deno.exe" if sys.platform == "win32" else "deno")
    return str(local) if local.exists() else shutil.which("deno")


class Downloader:
    def __init__(
        self,
        *,
        retries: int = 5,
        socket_timeout: float = 30,
        cookies_browser: str | None = None,
        ydl_factory: YdlFactory = yt_dlp.YoutubeDL,
    ) -> None:
        self.retries = retries
        self.socket_timeout = socket_timeout
        self.cookies_browser = cookies_browser
        self.ydl_factory = ydl_factory

    def _opts(self, logger: _Logger, **extra: Any) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            "noplaylist": True,
            "logger": logger,
            "retries": self.retries,
            "fragment_retries": self.retries,
            "extractor_retries": 2,
            "socket_timeout": self.socket_timeout,
            "consoletitle": False,
            "color": {"stdout": "never", "stderr": "never"},
        }
        if deno := _deno_path():
            opts["js_runtimes"] = {"deno": {"path": deno}}
        if self.cookies_browser:
            opts["cookiesfrombrowser"] = (self.cookies_browser,)
        opts.update(extra)
        return opts

    def _run(self, logger: _Logger, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except DownloadCancelled:
            raise
        except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as e:
            raise DownloadError("\n".join([*logger.errors, str(e)])) from None

    # ---------------------------------------------------------------- metadata
    def fetch_info(self, url: str, fallback: Platform = Platform.other) -> RemoteInfo:
        log = _Logger()
        with self.ydl_factory(self._opts(log, skip_download=True, format="bestaudio/best")) as ydl:
            info = self._run(log, lambda: ydl.extract_info(url, download=False))
        if not info:
            raise DownloadError("\n".join(log.errors) or "no information returned for this link")
        return parse_info(ydl.sanitize_info(info), fallback)

    # ---------------------------------------------------------------- downloads
    def _hook(self, progress: ProgressFn | None, is_cancelled: CancelFn | None) -> Any:
        def hook(d: dict[str, Any]) -> None:
            if is_cancelled and is_cancelled():
                raise DownloadCancelled
            if not progress or d.get("status") != "downloading":
                return
            done = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                progress(
                    min(99.0, done / total * 100),
                    f"downloading {done / 1e6:.1f} of {total / 1e6:.1f} MB",
                )
            elif d.get("fragment_count"):
                frac = (d.get("fragment_index") or 0) / d["fragment_count"]
                progress(
                    min(99.0, frac * 100),
                    f"downloading part {d.get('fragment_index')} of {d['fragment_count']}",
                )
            else:
                progress(-1, f"downloading {done / 1e6:.1f} MB")

        return hook

    def _download(
        self, url: str, out_dir: Path, stem: str, log: _Logger, opts: dict[str, Any]
    ) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob(f"{stem}.*"):
            old.unlink()
        opts["outtmpl"] = {"default": str(out_dir / f"{stem}.%(ext)s")}
        with self.ydl_factory(opts) as ydl:
            self._run(log, lambda: ydl.download([url]))
        files = [
            p for p in out_dir.glob(f"{stem}.*") if p.suffix not in (".part", ".ytdl", ".temp")
        ]
        if not files:
            raise DownloadError(
                "\n".join(log.errors) or "download finished but no file was written"
            )
        return max(files, key=lambda p: p.stat().st_mtime)

    def download_audio(
        self,
        url: str,
        out_dir: Path,
        window: Window | None = None,
        *,
        progress: ProgressFn | None = None,
        is_cancelled: CancelFn | None = None,
        stem: str = "audio",
    ) -> Path:
        """Best audio, converted to m4a. With a window only that range is fetched."""
        log = _Logger()
        extra: dict[str, Any] = {
            "format": "bestaudio/best",
            "progress_hooks": [self._hook(progress, is_cancelled)],
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}],
        }
        if window:
            extra["download_ranges"] = download_range_func(
                None, [(window.start_s, window.end_s or float("inf"))]
            )
            # Without this, ffmpeg stream-copies from the nearest earlier keyframe/cluster,
            # so the file can silently start seconds BEFORE window.start and every
            # transcript time would be shifted. Re-encoding at the cut makes it exact
            # (verified against the full audio by cross-correlation: 4.999 s for a 5 s cut).
            extra["force_keyframes_at_cuts"] = True
        return self._download(url, out_dir, stem, log, self._opts(log, **extra))

    def fetch_chat(self, url: str, out_dir: Path, *, stem: str = "chat") -> Path | None:
        """Chat replay as a file: YouTube `live_chat`, Twitch `rechat`. None if absent."""
        log = _Logger()
        out_dir.mkdir(parents=True, exist_ok=True)
        opts = self._opts(
            log,
            skip_download=True,
            writesubtitles=True,
            subtitleslangs=["live_chat", "rechat"],
            outtmpl={"default": str(out_dir / f"{stem}.%(ext)s")},
        )
        with self.ydl_factory(opts) as ydl:
            self._run(log, lambda: ydl.download([url]))
        found = sorted(
            p
            for p in out_dir.glob(f"{stem}.*")
            if p.suffix == ".json" and not p.name.endswith(".part")
        )
        return found[0] if found else None

    def download_proxy(
        self,
        url: str,
        out_dir: Path,
        window: Window | None = None,
        *,
        height: int = 360,
        progress: ProgressFn | None = None,
        is_cancelled: CancelFn | None = None,
        stem: str = "proxy_src",
    ) -> Path:
        """Small video-only copy for picture analysis (no audio needed)."""
        log = _Logger()
        extra: dict[str, Any] = {
            "format": f"bv*[height<={height}]/b[height<={height}]/wv*/w",
            "progress_hooks": [self._hook(progress, is_cancelled)],
        }
        if window:
            extra["download_ranges"] = download_range_func(
                None, [(window.start_s, window.end_s or float("inf"))]
            )
            extra["force_keyframes_at_cuts"] = True
        return self._download(url, out_dir, stem, log, self._opts(log, **extra))

    def download_section(
        self,
        url: str,
        out_dir: Path,
        start_s: float,
        end_s: float,
        *,
        max_height: int = 1080,
        progress: ProgressFn | None = None,
        is_cancelled: CancelFn | None = None,
        stem: str = "segment",
    ) -> Path:
        """Video+audio of [start, end] only, cut on exact frames, as mp4 (for rendering)."""
        log = _Logger()
        extra: dict[str, Any] = {
            "format": f"bv*[height<={max_height}]+ba/b[height<={max_height}]/bv*+ba/b",
            "merge_output_format": "mp4",
            "download_ranges": download_range_func(None, [(start_s, end_s)]),
            "force_keyframes_at_cuts": True,
            "progress_hooks": [self._hook(progress, is_cancelled)],
        }
        return self._download(url, out_dir, stem, log, self._opts(log, **extra))
