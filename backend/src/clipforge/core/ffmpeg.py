"""FFmpeg / ffprobe helpers.

`run_ffmpeg` streams `-progress` output to report percentage and kills the process
when the job is cancelled, so long encodes never block a cancel.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class FFmpegError(RuntimeError):
    pass


class FFmpegMissingError(FFmpegError):
    pass


class FFmpegCancelledError(FFmpegError):
    pass


def _exe(name: str) -> str:
    exe = shutil.which(name)
    if not exe:
        raise FFmpegMissingError(
            f"{name} not found on PATH. Windows: winget install Gyan.FFmpeg (then open a new "
            "terminal) | macOS: brew install ffmpeg | Linux: sudo apt install ffmpeg"
        )
    return exe


@dataclass
class StreamInfo:
    codec_type: str
    codec_name: str | None
    width: int | None = None
    height: int | None = None
    sample_rate: int | None = None
    channels: int | None = None


@dataclass
class MediaProbe:
    duration_s: float | None
    format_name: str | None
    size_bytes: int | None
    streams: list[StreamInfo] = field(default_factory=list)

    @property
    def has_video(self) -> bool:
        return any(s.codec_type == "video" for s in self.streams)

    @property
    def has_audio(self) -> bool:
        return any(s.codec_type == "audio" for s in self.streams)

    @property
    def video(self) -> StreamInfo | None:
        return next((s for s in self.streams if s.codec_type == "video"), None)


def _num(v: Any, cast: type[int] | type[float]) -> Any:
    try:
        return cast(v) if v not in (None, "N/A", "") else None
    except (TypeError, ValueError):
        return None


def probe(path: Path) -> MediaProbe:
    """Read container + stream info. Raises FFmpegError for unreadable/non-media files."""
    out = subprocess.run(
        [
            _exe("ffprobe"),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        stdin=subprocess.DEVNULL,  # never wait on an inherited console
        capture_output=True,
        text=True,
        timeout=120,
    )
    if out.returncode != 0:
        raise FFmpegError(f"not a readable media file: {out.stderr.strip()[:300]}")
    data = json.loads(out.stdout or "{}")
    fmt = data.get("format", {})
    streams = [
        StreamInfo(
            codec_type=s.get("codec_type", ""),
            codec_name=s.get("codec_name"),
            width=_num(s.get("width"), int),
            height=_num(s.get("height"), int),
            sample_rate=_num(s.get("sample_rate"), int),
            channels=_num(s.get("channels"), int),
        )
        for s in data.get("streams", [])
        # cover-art "video" streams in audio files are attached pictures, not video
        if not (s.get("disposition") or {}).get("attached_pic")
    ]
    return MediaProbe(
        duration_s=_num(fmt.get("duration"), float),
        format_name=fmt.get("format_name"),
        size_bytes=_num(fmt.get("size"), int),
        streams=streams,
    )


ProgressFn = Callable[[float], None]


def run_ffmpeg(
    args: Sequence[str],
    *,
    duration_s: float | None = None,
    on_progress: ProgressFn | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    timeout_s: float | None = None,
    cwd: Path | None = None,
) -> None:
    """Run ffmpeg with `args` (without the executable). Progress is 0..100 of `duration_s`.
    `cwd` lets filters reference files by bare name (no Windows drive-letter escaping)."""
    cmd = [
        _exe("ffmpeg"),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-progress",
        "pipe:1",
        "-nostats",
        *args,
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        cwd=cwd,
    )
    stderr_tail: list[str] = []

    def read_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_tail.append(line.rstrip())
            del stderr_tail[:-30]

    t = threading.Thread(target=read_stderr, daemon=True)
    t.start()
    cancelled = False
    timer = threading.Timer(timeout_s, proc.kill) if timeout_s else None
    if timer:
        timer.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if is_cancelled and is_cancelled():
                cancelled = True
                proc.kill()
                break
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and duration_s and on_progress and value.isdigit():
                on_progress(min(100.0, int(value) / 1e6 / duration_s * 100))
        proc.wait()
    finally:
        if timer:
            timer.cancel()
        t.join(timeout=5)
    if cancelled:
        raise FFmpegCancelledError("cancelled")
    if proc.returncode != 0:
        raise FFmpegError("ffmpeg failed: " + " | ".join(stderr_tail[-5:]))
    if on_progress:
        on_progress(100.0)


def extract_audio(
    src: Path,
    dst: Path,
    *,
    start_s: float | None = None,
    end_s: float | None = None,
    duration_s: float | None = None,
    on_progress: ProgressFn | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    """Audio-only copy for analysis: mono AAC 96 kb/s at 48 kHz (small, decodes fast)."""
    args: list[str] = []
    if start_s:
        args += ["-ss", f"{start_s:.3f}"]
    args += ["-i", str(src)]
    if end_s is not None:
        args += ["-t", f"{end_s - (start_s or 0):.3f}"]
    args += ["-vn", "-ac", "1", "-ar", "48000", "-c:a", "aac", "-b:a", "96k", str(dst)]
    span = (end_s - (start_s or 0)) if end_s is not None else duration_s
    run_ffmpeg(args, duration_s=span, on_progress=on_progress, is_cancelled=is_cancelled)


def cut_segment(
    src: Path,
    dst: Path,
    start_s: float,
    end_s: float,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    """Frame-accurate cut (re-encode) of [start, end] for rendering, keeps audio + video."""
    run_ffmpeg(
        [
            "-ss",
            f"{start_s:.3f}",
            "-i",
            str(src),
            "-t",
            f"{end_s - start_s:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(dst),
        ],
        duration_s=end_s - start_s,
        is_cancelled=is_cancelled,
    )
