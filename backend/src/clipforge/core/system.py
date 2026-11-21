"""System profile and environment checks ("doctor").

Detects what the machine can do (CPU, RAM, GPU, disk, ffmpeg) so the app can pick
safe defaults (e.g. light mode under 12 GB RAM) and explain missing prerequisites.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import psutil

LIGHT_MODE_RAM_GB = 12.0
MIN_FREE_DISK_GB = 10.0


@dataclass
class GpuInfo:
    name: str
    memory_total_mb: int
    driver: str


@dataclass
class SystemProfile:
    os: str
    python: str
    cpu_cores: int
    ram_gb: float
    disk_free_gb: float
    gpus: list[GpuInfo] = field(default_factory=list)
    ffmpeg: str | None = None
    ffprobe: str | None = None
    light_mode_recommended: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run(cmd: list[str], timeout: float = 10) -> str | None:
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        out = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def tool_version(name: str) -> str | None:
    out = _run([name, "-version"])
    if not out:
        return None
    m = re.search(rf"{name} version (\S+)", out)
    return m.group(1) if m else out.splitlines()[0]


def detect_gpus() -> list[GpuInfo]:
    out = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    gpus: list[GpuInfo] = []
    for line in (out or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[1].isdigit():
            gpus.append(GpuInfo(name=parts[0], memory_total_mb=int(parts[1]), driver=parts[2]))
    return gpus


def profile(data_dir: Path) -> SystemProfile:
    data_dir.mkdir(parents=True, exist_ok=True)
    ram_gb = round(psutil.virtual_memory().total / 1024**3, 1)
    return SystemProfile(
        os=f"{platform.system()} {platform.release()}",
        python=platform.python_version(),
        cpu_cores=psutil.cpu_count(logical=True) or 1,
        ram_gb=ram_gb,
        disk_free_gb=round(shutil.disk_usage(data_dir).free / 1024**3, 1),
        gpus=detect_gpus(),
        ffmpeg=tool_version("ffmpeg"),
        ffprobe=tool_version("ffprobe"),
        light_mode_recommended=ram_gb < LIGHT_MODE_RAM_GB,
    )


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str | None = None
    required: bool = True


def doctor(p: SystemProfile) -> list[Check]:
    install_ffmpeg = (
        "Windows: winget install Gyan.FFmpeg | macOS: brew install ffmpeg | "
        "Linux: sudo apt install ffmpeg (then open a new terminal)"
    )
    gpu = ", ".join(f"{g.name} ({g.memory_total_mb} MB)" for g in p.gpus)
    return [
        Check(
            "python",
            p.python.startswith("3.12"),
            p.python,
            "Use Python 3.12 (uv python install 3.12)",
        ),
        Check("ffmpeg", p.ffmpeg is not None, p.ffmpeg or "not found", install_ffmpeg),
        Check("ffprobe", p.ffprobe is not None, p.ffprobe or "not found", install_ffmpeg),
        Check(
            "disk",
            p.disk_free_gb >= MIN_FREE_DISK_GB,
            f"{p.disk_free_gb} GB free",
            f"Free at least {MIN_FREE_DISK_GB:.0f} GB or move CF_DATA_DIR",
        ),
        Check(
            "gpu",
            bool(p.gpus),
            gpu or "no NVIDIA GPU (CPU mode)",
            "Optional: an NVIDIA GPU makes transcription and encoding much faster",
            required=False,
        ),
        Check(
            "ram",
            not p.light_mode_recommended,
            f"{p.ram_gb} GB",
            "Under 12 GB: light mode will be used (1 render at a time, 30 fps)",
            required=False,
        ),
    ]
