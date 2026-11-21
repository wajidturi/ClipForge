"""Cover image: the most exciting frame with the hook written on it (1080x1920 JPEG)."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = (
    [r"C:\Windows\Fonts\ariblk.ttf", r"C:\Windows\Fonts\arialbd.ttf"]
    if sys.platform == "win32"
    else [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    ]
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    width: int,
) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        trial = f"{lines[-1]} {word}" if lines else word
        if lines and draw.textlength(trial, font=font) <= width:
            lines[-1] = trial
        else:
            lines.append(word)
    return lines


def make_cover(frame: Path, hook: str | None, out: Path) -> Path:
    img = Image.open(frame).convert("RGB")
    if img.size != (1080, 1920):
        img = img.resize((1080, 1920))
    if hook:
        draw = ImageDraw.Draw(img)
        font = _font(92)
        lines = _wrap(draw, hook.upper(), font, 900)
        y = 220
        for line in lines:
            w = draw.textlength(line, font=font)
            x = (1080 - w) / 2
            draw.rectangle([x - 28, y - 14, x + w + 28, y + 112], fill=(255, 255, 255))
            draw.text((x, y), line, font=font, fill=(17, 17, 17))
            y += 128
    img.save(out, "JPEG", quality=88)
    return out
