"""Pillow rasterisation of scene graphics (frames, dividers, layers, masks).

Every rule here has a twin in ``frontend/src/features/studio/draw.ts`` (same
constants, same shape points), so the canvas preview matches the export:

- text: font px = size*scale; line height 1.1*px; words wrap at max_width*1080;
  emoji runs use the emoji font; stroke = ``stroke`` px; shadow offset 0.06*px.
- shapes behind text: padding (0.42*px, 0.22*px) (tag: 0.32/0.16); box radius
  0.2*px; pill radius = height/2; ribbon skew = 0.35*height; burst = 16 spikes,
  outer radii alternating 1.0/0.9, inner 0.78, around an ellipse padded 1.3x/1.9x.
- italic = shear 0.21; then rotation around the centre; then opacity.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from clipforge.pipeline.render.fonts import font_path
from clipforge.pipeline.render.scene import H, Layer, Rect, Scene, W, panels

RGBA = tuple[int, int, int, int]


def rgba(hex_color: str, alpha: float = 1.0) -> RGBA:
    h = hex_color.lstrip("#")
    a = int(h[6:8], 16) if len(h) == 8 else 255
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(a * alpha))


# Colour bitmap emoji fonts (Noto Color Emoji on Linux) only open at their own size;
# glyphs are drawn at that size and scaled. Segoe UI Emoji (Windows) scales freely.
BITMAP_EMOJI_PX = 109


@lru_cache(maxsize=64)
def _font(font_id: str, px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    p = font_path(font_id)
    if p is None:
        return ImageFont.load_default(px)
    try:
        return ImageFont.truetype(str(p), px)
    except OSError:  # "invalid pixel size": a fixed-size bitmap font
        return ImageFont.truetype(str(p), BITMAP_EMOJI_PX)


def _ratio(f: ImageFont.FreeTypeFont | ImageFont.ImageFont, px: int) -> float:
    """How much a glyph drawn with `f` must be scaled to be `px` big (1 = as is)."""
    size = getattr(f, "size", px)
    return px / size if size and size != px else 1.0


def _length(f: ImageFont.FreeTypeFont | ImageFont.ImageFont, chunk: str, px: int) -> float:
    return f.getlength(chunk) * _ratio(f, px)


def _draw_scaled_emoji(
    target: Image.Image, xy: tuple[float, float], chunk: str, f: ImageFont.FreeTypeFont, px: int
) -> None:
    """Draw emoji at the font's own size, scale to `px`, paste on the baseline at `xy`."""
    ascent, descent = f.getmetrics()
    w = max(1, math.ceil(f.getlength(chunk)))
    tmp = Image.new("RGBA", (w, ascent + descent), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((0, ascent), chunk, font=f, anchor="ls", embedded_color=True)
    r = _ratio(f, px)
    size = (max(1, round(w * r)), max(1, round((ascent + descent) * r)))
    tmp = tmp.resize(size, Image.Resampling.LANCZOS)
    x, y = round(xy[0]), round(xy[1] - ascent * r)
    target.alpha_composite(tmp, (max(0, x), max(0, y)))


def is_emoji(ch: str) -> bool:
    o = ord(ch)
    return (
        o >= 0x1F000
        or 0x2600 <= o <= 0x27BF
        or 0x2B00 <= o <= 0x2BFF
        or o in (0x200D, 0xFE0F, 0x2122, 0x2139)
    )


def runs(text: str) -> list[tuple[str, bool]]:
    """Split into (chunk, is_emoji) runs."""
    out: list[tuple[str, bool]] = []
    for ch in text:
        e = is_emoji(ch) or (ch in "‍️" and bool(out) and out[-1][1])
        if out and out[-1][1] == e:
            out[-1] = (out[-1][0] + ch, e)
        else:
            out.append((ch, e))
    return out


# ------------------------------------------------------------------ text layout
@dataclass
class Line:
    text: str
    width: float


def _measure(text: str, font_id: str, px: int) -> float:
    total = 0.0
    for chunk, emo in runs(text):
        total += _length(_font("emoji" if emo else font_id, px), chunk, px)
    return total


def layout_lines(text: str, font_id: str, px: int, max_w: float) -> list[Line]:
    lines: list[Line] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            trial = f"{cur} {word}" if cur else word
            if cur and _measure(trial, font_id, px) > max_w:
                lines.append(Line(cur, _measure(cur, font_id, px)))
                cur = word
            else:
                cur = trial
        lines.append(Line(cur, _measure(cur, font_id, px)))
    return lines


def shape_points(shape: str, w: float, h: float) -> list[tuple[float, float]]:
    """Polygon (relative to the shape's top-left) for ribbon/burst; box-like shapes
    are drawn as rounded rectangles instead."""
    if shape == "ribbon":
        sk = 0.35 * h
        return [(sk, 0), (w, 0), (w - sk, h), (0, h)]
    if shape == "burst":
        cx, cy, n = w / 2, h / 2, 16
        pts = []
        for k in range(n * 2):
            a = -math.pi / 2 + k * math.pi / n
            r = (1.0 if (k // 2) % 2 == 0 else 0.9) if k % 2 == 0 else 0.78
            pts.append((cx + math.cos(a) * w / 2 * r, cy + math.sin(a) * h / 2 * r))
        return pts
    return []


def shape_box(shape: str, tw: float, th: float, px: int) -> tuple[float, float, float, float]:
    """(shape width, shape height, text offset x, text offset y) around a text block."""
    if shape == "none":
        return tw, th, 0, 0
    px_, py_ = (0.32 * px, 0.16 * px) if shape == "tag" else (0.42 * px, 0.22 * px)
    if shape == "burst":
        sw, sh = (tw + 2 * px_) * 1.38, (th + 2 * py_) * 1.8
    elif shape == "ribbon":
        sk = 0.35 * (th + 2 * py_)
        sw, sh = tw + 2 * px_ + sk, th + 2 * py_
    else:
        sw, sh = tw + 2 * px_, th + 2 * py_
    return sw, sh, (sw - tw) / 2, (sh - th) / 2


def _shear_rotate(img: Image.Image, italic: bool, rotation: float) -> Image.Image:
    if italic:
        k = 0.21
        extra = int(img.height * k) + 2
        canvas = Image.new("RGBA", (img.width + extra, img.height), (0, 0, 0, 0))
        canvas.paste(img, (extra // 2, 0))
        # x_src = x + k*(y - h/2): shears the top to the right (like canvas transform)
        img = canvas.transform(
            canvas.size,
            Image.Transform.AFFINE,
            (1, k, -k * canvas.height / 2, 0, 1, 0),
            resample=Image.Resampling.BICUBIC,
        )
    if rotation:
        img = img.rotate(-rotation, resample=Image.Resampling.BICUBIC, expand=True)
    return img


def render_text_layer(layer: Layer, text: str) -> Image.Image:
    """A text/emoji layer as a tight RGBA image (centre = layer position)."""
    px = max(8, round(layer.size * layer.scale))
    font_id = "emoji" if layer.kind == "emoji" else layer.font
    if layer.upper and layer.kind == "text":
        text = text.upper()
    lines = layout_lines(text or " ", font_id, px, layer.max_width * W)
    lh = px * 1.1
    tw = max(ln.width for ln in lines)
    th = lh * len(lines)
    sw, sh, ox, oy = shape_box(layer.shape, tw, th, px)
    margin = int(layer.stroke + px * 0.2 + 8)
    img = Image.new("RGBA", (int(sw + 2 * margin), int(sh + 2 * margin)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0 = margin, margin
    if layer.shape != "none":
        sstroke = max(3, int(px * 0.06)) if layer.shape_stroke else 0
        fill = rgba(layer.shape_color)
        outline = rgba(layer.shape_stroke) if layer.shape_stroke else None
        if layer.shape in ("ribbon", "burst"):
            pts = [(x0 + a, y0 + b) for a, b in shape_points(layer.shape, sw, sh)]
            d.polygon(pts, fill=fill, outline=outline, width=sstroke)
        else:
            radius = (
                sh / 2 if layer.shape == "pill" else (0.12 if layer.shape == "tag" else 0.2) * px
            )
            d.rounded_rectangle(
                [x0, y0, x0 + sw, y0 + sh],
                radius=radius,
                fill=fill,
                outline=outline,
                width=sstroke,
            )
    # text (shadow first, on its own layer so it can be blurred)
    text_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(text_img)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0)) if layer.shadow else None
    sd = ImageDraw.Draw(shadow) if shadow else None
    for i, ln in enumerate(lines):
        cx = x0 + ox + (tw - ln.width) / 2
        base = y0 + oy + i * lh + px * 0.86  # baseline
        for chunk, emo in runs(ln.text):
            f = _font("emoji" if emo else font_id, px)
            if emo and _ratio(f, px) != 1.0 and isinstance(f, ImageFont.FreeTypeFont):
                _draw_scaled_emoji(text_img, (cx, base), chunk, f, px)
            elif emo:
                td.text((cx, base), chunk, font=f, anchor="ls", embedded_color=True)
            else:
                td.text(
                    (cx, base),
                    chunk,
                    font=f,
                    fill=rgba(layer.color),
                    anchor="ls",
                    stroke_width=layer.stroke,
                    stroke_fill=rgba(layer.stroke_color),
                )
                if sd is not None:
                    sd.text(
                        (cx, base + px * 0.06),
                        chunk,
                        font=f,
                        fill=(0, 0, 0, 150),
                        anchor="ls",
                        stroke_width=layer.stroke,
                        stroke_fill=(0, 0, 0, 150),
                    )
            cx += _length(f, chunk, px)
    if shadow is not None:
        img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(px * 0.05)))
    img = Image.alpha_composite(img, text_img)
    img = _shear_rotate(img, layer.italic, layer.rotation)
    return _opacity(img, layer.opacity)


def render_image_layer(layer: Layer, path: Path) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    w = max(4, round(layer.width * W * layer.scale))
    h = max(4, round(img.height * w / img.width))
    img = img.resize((w, h), Image.Resampling.LANCZOS)
    img = _shear_rotate(img, False, layer.rotation)
    return _opacity(img, layer.opacity)


def _opacity(img: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 0.999:
        return img
    a = img.getchannel("A").point(lambda v: int(v * opacity))
    img.putalpha(a)
    return img


# ------------------------------------------------------------------ template graphics
def _rounded_mask(size: tuple[int, int], rects: list[tuple[Rect, int]]) -> Image.Image:
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    for r, rad in rects:
        d.rounded_rectangle([r.x, r.y, r.x + r.w - 1, r.y + r.h - 1], radius=rad, fill=255)
    return m


def _glow_outline(
    base: Image.Image,
    rect: Rect,
    radius: int,
    color: str,
    color2: str,
    width: int,
    glow: int,
    *,
    circle: bool = False,
) -> None:
    if width <= 0:
        return
    box = [rect.x, rect.y, rect.x + rect.w - 1, rect.y + rect.h - 1]
    if glow > 0:
        g = Image.new("RGBA", base.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(g)
        if circle:
            gd.ellipse(box, outline=rgba(color2), width=width + glow // 2)
        else:
            gd.rounded_rectangle(box, radius=radius, outline=rgba(color2), width=width + glow // 2)
        base.alpha_composite(g.filter(ImageFilter.GaussianBlur(glow / 2)))
    d = ImageDraw.Draw(base)
    if circle:
        d.ellipse(box, outline=rgba(color), width=width)
    else:
        d.rounded_rectangle(box, radius=radius, outline=rgba(color), width=width)


def divider_points(scene: Scene) -> list[tuple[float, float]]:
    """The dual-vision divider band: a slightly tilted quad across the split line."""
    dv = scene.regions.divider
    yc = H * scene.regions.split
    half = dv.thickness / 2
    dy = math.tan(math.radians(dv.tilt)) * W / 2
    return [
        (-10, yc - half + dy),
        (W + 10, yc - half - dy),
        (W + 10, yc + half - dy),
        (-10, yc + half + dy),
    ]


def frame_image(scene: Scene) -> Image.Image | None:
    """Background around panels, neon borders, the cam ring, the divider, letterbox
    bars and the vignette, as one 1080x1920 RGBA overlay."""
    r, fx = scene.regions, scene.effects
    fr = r.frame
    p = panels(scene)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    stacked = scene.template in ("streamer_first", "gameplay_first", "dual_vision")
    drew = False
    if fr.style != "none" and (stacked or fr.gap > 0 or fr.radius > 0):
        holes = [(p["game"], fr.radius)] + ([(p["cam"], fr.radius)] if stacked else [])
        bg = Image.new("RGBA", (W, H), rgba(fr.background))
        bg.putalpha(Image.eval(_rounded_mask((W, H), holes), lambda v: 255 - v))
        img.alpha_composite(bg)
        drew = True
    if fr.style != "none":
        for key in ("cam", "game") if stacked else ("game",):
            rect = p[key]
            glow = fr.glow if fr.style == "neon" else 0
            _glow_outline(img, rect, fr.radius, fr.color, fr.color2, fr.width, glow)
        drew = True
    if scene.template == "floating_facecam" and "cam" in p and r.cam.border_width > 0:
        c = r.cam
        radius = 0 if c.shape == "square" else int(p["cam"].w * 0.22)
        _glow_outline(
            img,
            p["cam"],
            radius,
            c.border_color,
            c.border_color,
            c.border_width,
            c.glow,
            circle=c.shape == "circle",
        )
        drew = True
    if scene.template == "dual_vision" and r.divider.style != "none":
        _divider(img, scene)
        drew = True
    if fx.letterbox:
        d = ImageDraw.Draw(img)
        bar = int(H * 0.085)
        d.rectangle([0, 0, W, bar], fill=(0, 0, 0, 255))
        d.rectangle([0, H - bar, W, H], fill=(0, 0, 0, 255))
        drew = True
    if fx.vignette:
        img.alpha_composite(_vignette())
        drew = True
    return img if drew else None


def _divider(img: Image.Image, scene: Scene) -> None:
    dv = scene.regions.divider
    pts = divider_points(scene)
    if dv.style == "line":
        yc = H * scene.regions.split
        dy = math.tan(math.radians(dv.tilt)) * W / 2
        d = ImageDraw.Draw(img)
        d.line([(0, yc + dy), (W, yc - dy)], fill=rgba(dv.color), width=max(4, dv.thickness // 8))
        return
    # horizontal gradient colour -> colour2, clipped to the band
    grad = np.zeros((H, W, 4), dtype=np.uint8)
    c1, c2 = np.array(rgba(dv.color), float), np.array(rgba(dv.color2), float)
    ramp = np.linspace(0, 1, W)[None, :, None]
    grad[:] = (c1 * (1 - ramp) + c2 * ramp).astype(np.uint8)
    band = Image.new("L", (W, H), 0)
    ImageDraw.Draw(band).polygon(pts, fill=255)
    layer = Image.fromarray(grad, "RGBA")
    layer.putalpha(band)
    if dv.style == "ribbon":  # soft glow under the ribbon
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).polygon(pts, fill=rgba(dv.color2, 0.8))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)))
    img.alpha_composite(layer)
    d = ImageDraw.Draw(img)
    d.line([pts[0], pts[1]], fill=(255, 255, 255, 200), width=3)
    d.line([pts[3], pts[2]], fill=(255, 255, 255, 200), width=3)


@lru_cache(maxsize=1)
def _vignette() -> Image.Image:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dx, dy = (xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2)
    d = np.sqrt(dx * dx + dy * dy) / math.sqrt(2)
    a = np.clip((d - 0.45) / 0.55, 0, 1) ** 1.6 * 200
    arr = np.zeros((H, W, 4), dtype=np.uint8)
    arr[..., 3] = a.astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def cam_mask(side: int, shape: str) -> Image.Image:
    m = Image.new("L", (side, side), 0)
    d = ImageDraw.Draw(m)
    if shape == "circle":
        d.ellipse([0, 0, side - 1, side - 1], fill=255)
    elif shape == "rounded":
        d.rounded_rectangle([0, 0, side - 1, side - 1], radius=int(side * 0.22), fill=255)
    else:
        d.rectangle([0, 0, side - 1, side - 1], fill=255)
    return m


def speed_lines() -> Image.Image:
    """Radial streaks from the centre (deterministic: golden-angle spacing)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = W / 2, H / 2
    for k in range(64):
        a = math.radians((k * 137.508) % 360)
        r0 = 380 + (k * 53) % 260
        r1 = r0 + 420 + (k * 97) % 600
        wdt = 3 + k % 4
        d.line(
            [
                (cx + math.cos(a) * r0, cy + math.sin(a) * r0),
                (cx + math.cos(a) * r1, cy + math.sin(a) * r1),
            ],
            fill=(255, 255, 255, 150),
            width=wdt,
        )
    return img


# ------------------------------------------------------------------ facecam backgrounds
def _hex(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _vgrad(w: int, h: int, stops: list[tuple[float, str]]) -> np.ndarray:
    """Vertical gradient through colour stops (position 0..1 from the top)."""
    ys = np.linspace(0, 1, h)[:, None]
    pos = [p for p, _ in stops]
    out = np.zeros((h, 1, 3), np.float32)
    for ch in range(3):
        vals = [_hex(c)[ch] for _, c in stops]
        out[:, :, ch] = np.interp(ys, pos, vals)
    return np.repeat(out, w, axis=1)


def _glow(img: Image.Image, draw: Callable[[ImageDraw.ImageDraw], None], blur: float) -> None:
    """Draw shapes on a layer, blur it and add it on top (light, not paint)."""
    layer = Image.new("RGB", img.size, (0, 0, 0))
    draw(ImageDraw.Draw(layer))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    a = np.asarray(img, np.float32) + np.asarray(layer, np.float32)
    img.paste(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)))


@lru_cache(maxsize=64)
def cam_background(bg: str, w: int, h: int) -> Image.Image:
    """A picture behind the cut-out streamer. Drawn, not loaded: no image files, any
    size, same result every time (the studio preview fetches the same PNG)."""
    w, h = max(2, w), max(2, h)
    s = min(w, h)
    rng = np.random.default_rng(7)

    def base(stops: list[tuple[float, str]]) -> Image.Image:
        return Image.fromarray(_vgrad(w, h, stops).astype(np.uint8))

    if bg == "neon_purple":
        img = base([(0, "#12052E"), (0.6, "#3B0F78"), (1, "#7C3AED")])

        def streaks(d: ImageDraw.ImageDraw) -> None:
            for i, c in enumerate(("#22D3EE", "#F472B6", "#A78BFA")):
                x0 = w * (0.1 + 0.35 * i)
                d.line([(x0, h), (x0 + w * 0.5, 0)], fill=_hex(c), width=max(2, s // 40))

        _glow(img, streaks, s / 30)
    elif bg == "cyber_blue":
        img = base([(0, "#020617"), (0.55, "#0B1E4A"), (1, "#0E4A7A")])

        def grid(d: ImageDraw.ImageDraw) -> None:
            hy = h * 0.55  # horizon
            for i in range(-8, 9):  # lines to the vanishing point
                d.line([(w / 2, hy), (w / 2 + i * w / 4, h)], fill=(34, 211, 238), width=2)
            for k in range(1, 8):
                y = hy + (h - hy) * (k / 8) ** 1.8
                d.line([(0, y), (w, y)], fill=(34, 211, 238), width=2)
            d.line([(0, hy), (w, hy)], fill=(125, 249, 255), width=max(2, s // 120))

        _glow(img, grid, 1.2)
    elif bg == "sunset":
        img = base([(0, "#2E1065"), (0.45, "#DB2777"), (0.75, "#F97316"), (1, "#FDBA74")])

        def sun(d: ImageDraw.ImageDraw) -> None:
            r = s * 0.28
            d.ellipse([w / 2 - r, h * 0.62 - r, w / 2 + r, h * 0.62 + r], fill=(120, 70, 20))

        _glow(img, sun, s / 14)
    elif bg == "midnight":
        img = base([(0, "#030712"), (0.7, "#0F1B44"), (1, "#1E3A8A")])

        def stars(d: ImageDraw.ImageDraw) -> None:
            for _ in range(int(w * h / 2500)):
                x, y = rng.uniform(0, w), rng.uniform(0, h * 0.85)
                r = rng.uniform(0.6, 2.0) * s / 600
                v = int(rng.uniform(120, 255))
                d.ellipse([x - r, y - r, x + r, y + r], fill=(v, v, v))

        _glow(img, stars, 0.6)
    elif bg == "studio_gray":
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d = np.hypot((xx - w / 2) / w, (yy - h * 0.45) / h)
        v = np.clip(150 - d * 190, 28, 150)
        img = Image.fromarray(np.dstack([v, v, v * 1.04]).clip(0, 255).astype(np.uint8))
    elif bg == "red_rush":
        img = base([(0, "#0A0A0A"), (0.6, "#450A0A"), (1, "#B91C1C")])

        def stripes(d: ImageDraw.ImageDraw) -> None:
            for i in range(9):
                x = w * (i / 6 - 0.4)
                d.polygon(
                    [(x, h), (x + w * 0.05, h), (x + w * 0.75, 0), (x + w * 0.7, 0)],
                    fill=(90, 8, 8),
                )

        _glow(img, stripes, s / 80)
    elif bg == "aurora":
        img = base([(0, "#04121A"), (1, "#0B2530")])

        def blobs(d: ImageDraw.ImageDraw) -> None:
            for cx, cy, rx, ry, c in (
                (0.25, 0.3, 0.45, 0.18, (16, 160, 110)),
                (0.7, 0.45, 0.4, 0.16, (110, 40, 170)),
                (0.45, 0.65, 0.5, 0.14, (20, 120, 160)),
            ):
                d.ellipse([w * (cx - rx), h * (cy - ry), w * (cx + rx), h * (cy + ry)], fill=c)

        _glow(img, blobs, s / 7)
    elif bg == "gold_lux":
        img = base([(0, "#0C0A09"), (1, "#292016")])

        def bokeh(d: ImageDraw.ImageDraw) -> None:
            for _ in range(28):
                x, y = rng.uniform(0, w), rng.uniform(0, h)
                r = rng.uniform(0.03, 0.09) * s
                k = rng.uniform(0.35, 0.9)
                d.ellipse([x - r, y - r, x + r, y + r], fill=(int(200 * k), int(150 * k), 40))

        _glow(img, bokeh, s / 45)
    else:
        raise ValueError(f"no picture for background '{bg}'")
    return img
