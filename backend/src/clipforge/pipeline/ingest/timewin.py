"""Time parsing for source windows: "90", "1:30", "1:02:03", "1:00:00-1:30:00"."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TIME = re.compile(r"^\s*(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)\s*$")


class InvalidTimeError(ValueError):
    pass


def parse_time(text: str | float | int) -> float:
    """Seconds from `ss`, `mm:ss` or `hh:mm:ss` (fractions allowed on seconds)."""
    if isinstance(text, (int, float)):
        if text < 0:
            raise InvalidTimeError("time cannot be negative")
        return float(text)
    m = _TIME.match(text)
    if not m:
        raise InvalidTimeError(f"'{text}' is not a time (use 90, 1:30 or 1:02:03)")
    a, b, s = m.groups()
    sec = float(s)
    if b is not None:  # hh:mm:ss
        h, mnt = int(a), int(b)
        if mnt >= 60:
            raise InvalidTimeError(f"'{text}': minutes must be under 60")
    else:  # mm:ss (minutes may exceed 59, e.g. 90:00) or plain seconds
        h, mnt = 0, int(a) if a is not None else 0
    if a is not None and sec >= 60:
        raise InvalidTimeError(f"'{text}': seconds must be under 60")
    return h * 3600 + mnt * 60 + sec


def format_time(seconds: float) -> str:
    s = round(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


@dataclass(frozen=True)
class Window:
    start_s: float
    end_s: float | None  # None = until the end

    @property
    def length_s(self) -> float | None:
        return None if self.end_s is None else self.end_s - self.start_s

    def clamp(self, duration_s: float | None) -> Window:
        if duration_s is None:
            return self
        if self.start_s >= duration_s:
            raise InvalidTimeError(
                f"window starts at {format_time(self.start_s)} but the video is only "
                f"{format_time(duration_s)} long"
            )
        end = duration_s if self.end_s is None else min(self.end_s, duration_s)
        return Window(self.start_s, end)


def make_window(start: str | float | None, end: str | float | None) -> Window | None:
    if start in (None, "") and end in (None, ""):
        return None
    s = parse_time(start) if start not in (None, "") else 0.0
    e = parse_time(end) if end not in (None, "") else None
    if e is not None and e <= s:
        raise InvalidTimeError("the end time must be after the start time")
    if e is not None and e - s < 10:
        raise InvalidTimeError("a window must be at least 10 seconds long")
    return Window(s, e)


def parse_window(text: str) -> Window | None:
    """'1:00:00-1:30:00' or '45:00-' (until the end)."""
    if not text or not text.strip():
        return None
    if "-" not in text:
        raise InvalidTimeError("write a window as START-END, e.g. 1:00:00-1:30:00")
    a, _, b = text.partition("-")
    return make_window(a, b)


def default_window(
    duration_s: float | None, max_hours: float, default_hours: float
) -> Window | None:
    """Over-long sources (e.g. 8 h VODs) get the last `default_hours` by default."""
    if duration_s is None or duration_s <= max_hours * 3600:
        return None
    return Window(max(0.0, duration_s - default_hours * 3600), duration_s)
