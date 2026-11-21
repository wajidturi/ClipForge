"""Generate small real media files with FFmpeg for tests (no binary fixtures in git)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


def make_video(path: Path, seconds: float = 20, *, audio: bool = True) -> Path:
    args = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=640x360:rate=25:duration={seconds}",
    ]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    args += ["-c:a", "aac", "-shortest"] if audio else ["-an"]
    subprocess.run([*args, str(path)], check=True)
    return path


def make_audio(path: Path, seconds: float = 15) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=330:duration={seconds}",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )
    return path
