"""Small visual/audio effects expressed as ffmpeg expressions and filters."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from clipforge.core.ffmpeg import FFmpegError, _exe


def zoom_expression(
    peaks: list[float],
    *,
    amount: float = 0.10,
    rise: float = 0.2,
    hold: float = 0.9,
    fall: float = 0.4,
) -> str:
    """Scale factor in `t`: 1.0, punching in by `amount` around each peak (output seconds)."""
    if not peaks:
        return "1"
    bumps = [
        f"clip((t-{p - rise:.3f})/{rise},0,1)*clip(({p + hold + fall:.3f}-t)/{fall},0,1)"
        for p in sorted(peaks)
    ]
    return f"1+{amount}*min(1,{'+'.join(bumps)})"


def pick_peaks(
    times: list[float], duration: float, *, min_gap: float = 4.0, edge: float = 1.5, limit: int = 3
) -> list[float]:
    """At most `limit` peaks, not too close to each other or to the edges."""
    out: list[float] = []
    for t in times:
        if edge <= t <= duration - edge and all(abs(t - o) >= min_gap for o in out):
            out.append(t)
        if len(out) >= limit:
            break
    return sorted(out)


TARGET_LUFS = -14.0
# Light denoise, then a gentle compressor so a few shouted peaks do not stop the
# gain from reaching the target (that is why loudnorm alone undershoots on streams).
PRE_CHAIN = "afftdn=nf=-25,acompressor=threshold=0.125:ratio=3:attack=5:release=150:makeup=1"
LIMITER = "alimiter=limit=0.891:level=false"  # -1 dBFS ceiling


def integrated_lufs(media: Path, chain: str) -> float | None:
    """EBU R128 integrated loudness of `media` after the audio filter `chain`."""
    out = subprocess.run(
        [
            _exe("ffmpeg"),
            "-hide_banner",
            "-nostdin",
            "-i",
            str(media),
            "-vn",
            "-af",
            f"{chain},ebur128=framelog=quiet",
            "-f",
            "null",
            "-",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if out.returncode != 0:
        raise FFmpegError("loudness measurement failed: " + out.stderr[-300:])
    found = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", out.stderr)
    return float(found[-1]) if found and found[-1] != "-inf" else None


def _chain(gain: float) -> str:
    return f"{PRE_CHAIN},volume={gain:.2f}dB,{LIMITER}"


def measure_loudness(media: Path, *, tolerance: float = 0.5, rounds: int = 3) -> dict[str, str]:
    """Find the static gain that lands on -14 LUFS *after* the limiter.

    The limiter shaves loud peaks, which lowers the integrated loudness, so one
    measurement is not enough: measure, correct the remaining difference, repeat
    (audio only, a few seconds for a Short)."""
    base = integrated_lufs(media, PRE_CHAIN)
    if base is None:
        return {"gain_db": "0", "input_i": "-inf"}
    gain = max(-20.0, min(30.0, TARGET_LUFS - base))
    result = base + gain
    for _ in range(rounds):
        result = integrated_lufs(media, _chain(gain)) or result
        if abs(result - TARGET_LUFS) <= tolerance:
            break
        gain = max(-20.0, min(36.0, gain + (TARGET_LUFS - result)))
    return {"gain_db": f"{gain:.2f}", "input_i": f"{base:.2f}", "expected_i": f"{result:.2f}"}


def audio_chain(measured: dict[str, str] | None) -> str:
    """PRE_CHAIN -> static gain to -14 LUFS -> -1 dBFS peak limiter.

    A static gain keeps speech dynamics natural; loudnorm's dynamic mode undershoots
    on clips shorter than ~30 s, which QC caught on the first test renders."""
    gain = float(measured.get("gain_db", 0)) if measured else 0.0
    return _chain(gain) + ",aresample=48000"
