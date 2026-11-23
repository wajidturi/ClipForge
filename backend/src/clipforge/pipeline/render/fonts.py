"""Fonts shared by the renderer (Pillow + libass) and the browser preview.

The browser loads the very same files through ``GET /api/v1/fonts/{id}`` under the
family name ``cf-<id>``, so what the studio shows is what FFmpeg burns in.
On Windows the system fonts are used; elsewhere DejaVu is the fallback.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

WIN = Path(r"C:\Windows\Fonts")
LINUX_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
LINUX_EMOJI = Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")


@dataclass(frozen=True)
class Font:
    id: str
    label: str
    family: str  # family name as libass knows it
    bold: bool  # ASS Bold flag for this family
    win_file: str
    category: str  # headline | text | fun | serif | emoji


FONTS: dict[str, Font] = {
    f.id: f
    for f in [
        Font("impact", "Impact (gaming headline)", "Impact", False, "impact.ttf", "headline"),
        Font("arial_black", "Arial Black", "Arial Black", False, "ariblk.ttf", "headline"),
        Font("segoe_black", "Segoe UI Black", "Segoe UI Black", False, "seguibl.ttf", "headline"),
        Font(
            "franklin", "Franklin Gothic", "Franklin Gothic Medium", False, "framd.ttf", "headline"
        ),
        Font("segoe_bold", "Segoe UI Bold", "Segoe UI", True, "segoeuib.ttf", "text"),
        Font("trebuchet", "Trebuchet Bold", "Trebuchet MS", True, "trebucbd.ttf", "text"),
        Font("verdana", "Verdana Bold", "Verdana", True, "verdanab.ttf", "text"),
        Font("comic", "Comic Bold (fun)", "Comic Sans MS", True, "comicbd.ttf", "fun"),
        Font("georgia", "Georgia Bold (cinematic)", "Georgia", True, "georgiab.ttf", "serif"),
        Font("emoji", "Emoji", "Segoe UI Emoji", False, "seguiemj.ttf", "emoji"),
    ]
}
DEFAULT_FONT = "impact"


@lru_cache
def font_path(font_id: str) -> Path | None:
    f = FONTS.get(font_id) or FONTS[DEFAULT_FONT]
    if sys.platform == "win32":
        p = WIN / f.win_file
        if p.exists():
            return p
    fallback = LINUX_EMOJI if f.id == "emoji" else LINUX_BOLD
    return fallback if fallback.exists() else None


def available() -> list[Font]:
    return [f for f in FONTS.values() if font_path(f.id) is not None]


def ass_family(font_id: str) -> tuple[str, bool]:
    """(family, bold) for an ASS style line."""
    f = FONTS.get(font_id) or FONTS[DEFAULT_FONT]
    if sys.platform != "win32":
        return "DejaVu Sans", True
    return f.family, f.bold
