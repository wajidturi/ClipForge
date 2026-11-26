"""Render a scene on top of a cut (the fast "compose" stage).

Draw order (the browser preview uses the same order):
panels (game, facecam) -> zoom punch -> colour -> frame graphics -> speed lines ->
captions -> layers (list order) -> shake -> flash -> glitch.

Layer animation formulas (u = t - start):
- pop  : scale 0.3 -> 1.15 in 0.22 s, back to 1.0 by 0.37 s; alpha fades in 0.12 s
- zoom : scale 1.8 -> 1.0 in 0.3 s; alpha 0.2 s
- fade : alpha 0.3 s
- slide_*: offset eased (1-(1-x)^3) over 0.35 s from 220 px (up/down) or 700 px
- pulse: scale x (1 + 0.06 sin(2pi 1.6 u)); shake: +-6/4 px; float: +-10 px vertical
- anim_out fade: alpha -> 0 over the last 0.25 s
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clipforge.core import ffmpeg
from clipforge.pipeline.render import captions, compose, raster
from clipforge.pipeline.render.edl import CaptionWord
from clipforge.pipeline.render.effects import audio_chain, zoom_expression
from clipforge.pipeline.render.reframe import Box, track_targets, x_expression
from clipforge.pipeline.render.scene import (
    CAM_MAX_GROW,
    H,
    Layer,
    Rect,
    Scene,
    W,
    cam_tiles,
    cover_crop,
    fill_text,
    panels,
)

FPS = compose.FPS
IN_DUR = {"pop": 0.37, "zoom": 0.3, "fade": 0.3, "none": 0.0}
ALPHA_IN = {"pop": 0.12, "zoom": 0.2, "fade": 0.3, "none": 0.0}
SLIDE = {
    "slide_up": (0, 220),
    "slide_down": (0, -220),
    "slide_left": (700, 0),
    "slide_right": (-700, 0),
}


@dataclass
class CutPlan:
    src_w: int
    src_h: int
    duration: float
    cam: Box | None
    targets: list[tuple[float, float | None]]
    cuts: list[float]
    zoom_peaks: list[float]
    measured: dict[str, str] | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    cams: list[Box] = field(default_factory=list)  # every facecam / person, left to right
    cam_kind: str = "overlay"

    def cam_list(self, template: str) -> list[Box]:
        """What the facecam panel shows: everyone side by side in stacked templates,
        the main person in the floating bubble."""
        cams = self.cams or ([self.cam] if self.cam else [])
        if template == "floating_facecam":
            main = self.cam if self.cam in cams else (cams[0] if cams else None)
            return [main] if main else []
        return cams


# ------------------------------------------------------------------ animation exprs
def _scale_expr(ly: Layer) -> tuple[str | None, float]:
    u = f"max(0,t-{ly.start:.3f})"
    parts, mx = [], 1.0
    if ly.anim_in == "pop":
        parts.append(
            f"if(lt({u},0.22),0.3+0.85*{u}/0.22,if(lt({u},0.37),1.15-0.15*({u}-0.22)/0.15,1))"
        )
        mx = 1.15
    elif ly.anim_in == "zoom":
        parts.append(f"if(lt({u},0.3),1.8-0.8*{u}/0.3,1)")
        mx = 1.8
    if ly.loop == "pulse":
        parts.append(f"(1+0.06*sin(2*PI*1.6*{u}))")
        mx *= 1.06
    return ("*".join(parts) if parts else None), mx


def _offset_exprs(ly: Layer) -> tuple[str, str]:
    u = f"max(0,t-{ly.start:.3f})"
    dx, dy = ["0"], ["0"]
    if ly.anim_in in SLIDE:
        ox, oy = SLIDE[ly.anim_in]
        ease = f"(1-pow(1-clip({u}/0.35,0,1),3))"
        if ox:
            dx.append(f"{ox}*(1-{ease})")
        if oy:
            dy.append(f"{oy}*(1-{ease})")
    if ly.loop == "shake":
        dx.append(f"6*sin(2*PI*9*{u})")
        dy.append(f"4*sin(2*PI*13*{u}+1)")
    elif ly.loop == "float":
        dy.append(f"10*sin(2*PI*0.8*{u})")
    return "+".join(dx), "+".join(dy)


def _windows(moments: list[float], length: float) -> str:
    return "+".join(f"between(t,{m:.3f},{m + length:.3f})" for m in moments) or "0"


def _decay(moments: list[float], length: float) -> str:
    return (
        "+".join(f"between(t,{m:.3f},{m + length:.3f})*(1-(t-{m:.3f})/{length})" for m in moments)
        or "0"
    )


# ------------------------------------------------------------------ graph
@dataclass
class Built:
    graph: str
    inputs: list[list[str]]  # extra ffmpeg input args, in order (input 1, 2, ...)


def _game_chain(plan: CutPlan, rect: Rect, fit: str, label: str, src: str) -> list[str]:
    if fit == "blur":
        return [
            f"{src}split[gb{label}][gf{label}]",
            f"[gb{label}]scale={rect.w}:{rect.h}:force_original_aspect_ratio=increase,"
            f"crop={rect.w}:{rect.h},boxblur=24:2,eq=brightness=-0.14[gbb{label}]",
            f"[gf{label}]scale={rect.w}:{rect.h}:force_original_aspect_ratio=decrease,setsar=1[gff{label}]",
            f"[gbb{label}][gff{label}]overlay=(W-w)/2:(H-h)/2[{label}]",
        ]
    ar = rect.w / rect.h
    ch = plan.src_h
    cw = compose._even(ch * ar)
    if cw > plan.src_w:
        cw = compose._even(plan.src_w)
        ch = compose._even(cw / ar)
    keys = track_targets(plan.targets, plan.cuts, min(1.0, cw / plan.src_w))
    x = x_expression(keys, float(plan.src_w))
    y = (plan.src_h - ch) // 2
    return [f"{src}crop={cw}:{ch}:'{x}':{y},scale={rect.w}:{rect.h},setsar=1[{label}]"]


HIDE_GROW = 1.15  # cam boxes come from the face, so cover a little more of the overlay


def hide_rects(cams: list[Box], src_w: int, src_h: int) -> list[tuple[int, int, int, int]]:
    """Source pixels (x, y, w, h) of each facecam overlay, slightly enlarged."""
    out = []
    for c in cams:
        b = c.expand(HIDE_GROW, HIDE_GROW)
        x, y = int(b.x * src_w), int(b.y * src_h)
        w = compose._even(min(b.w * src_w, src_w - x))
        h = compose._even(min(b.h * src_h, src_h - y))
        if w >= 8 and h >= 8:
            out.append((x, y, w, h))
    return out


def hide_cams(cams: list[Box], src_w: int, src_h: int, src: str, out: str) -> list[str]:
    """Blur the facecam overlays inside the gameplay, so a game crop that reaches a
    corner does not show a second, cut-off copy of the streamer."""
    rects = hide_rects(cams, src_w, src_h)
    if not rects:
        return [f"{src}copy{out}"]
    g = [f"{src}split={len(rects) + 1}[hb]" + "".join(f"[hc{i}]" for i in range(len(rects)))]
    base = "[hb]"
    for i, (x, y, w, h) in enumerate(rects):
        r = max(2, min(20, w // 8, h // 8))
        g.append(f"[hc{i}]crop={w}:{h}:{x}:{y},boxblur={r}:3,eq=brightness=-0.08[hz{i}]")
        nxt = out if i == len(rects) - 1 else f"[hd{i}]"
        g.append(f"{base}[hz{i}]overlay={x}:{y}{nxt}")
        base = nxt
    return g


def build_graph(
    scene: Scene,
    plan: CutPlan,
    workdir: Path,
    *,
    words: list[CaptionWord],
    keywords: list[str],
    values: dict[str, str | None],
    image_path: Callable[[str], Path | None],
) -> Built:
    d = plan.duration
    inputs: list[list[str]] = []

    def add_image(path: Path) -> str:
        inputs.append(["-loop", "1", "-framerate", str(FPS), "-t", f"{d:.3f}", "-i", str(path)])
        return f"[{len(inputs)}:v]"

    p = panels(scene)
    fit = scene.regions.fit if scene.template in ("floating_facecam", "cinematic") else "fill"
    cams = plan.cam_list(scene.template) if "cam" in p else []
    tiles = cam_tiles(p["cam"], len(cams)) if cams else []
    g: list[str] = [
        f"[0:v]fps={FPS},split={1 + len(cams)}[sg]" + "".join(f"[sc{i}]" for i in range(len(cams)))
    ]
    game_src = "[sg]"
    if cams and plan.cam_kind == "overlay":  # the cams have their own panel: blur them here
        g += hide_cams(plan.cams, plan.src_w, plan.src_h, "[sg]", "[sgh]")
        game_src = "[sgh]"
    fx = scene.effects
    gr = p["game"]
    z = zoom_expression(plan.zoom_peaks, amount=fx.zoom_amount) if fx.zoom_punch else "1"
    if z != "1":  # punch-in on the gameplay only (frames and the facecam stay put)
        g += _game_chain(plan, gr, fit, "game0", game_src)
        g.append(
            f"[game0]scale=w='2*trunc({gr.w / 2}*({z}))':h='2*trunc({gr.h / 2}*({z}))':"
            f"eval=frame,crop={gr.w}:{gr.h}[game]"
        )
    else:
        g += _game_chain(plan, gr, fit, "game", game_src)
    full = p["game"] == Rect(0, 0, W, H)
    if full:
        base = "[game]"
    else:
        bg = scene.regions.frame.background.lstrip("#")[:6]
        g.append(f"color=c=0x{bg}:s={W}x{H}:r={FPS}:d={d:.3f}[canvas]")
        g.append(f"[canvas][game]overlay={p['game'].x}:{p['game'].y}:shortest=1[b0]")
        base = "[b0]"
    for i, (cam, r) in enumerate(zip(cams, tiles, strict=True)):
        x, y, cw, ch = cover_crop(
            (cam.x, cam.y, cam.w, cam.h), r.w / r.h, plan.src_w, plan.src_h, CAM_MAX_GROW
        )
        g.append(f"[sc{i}]crop={cw}:{ch}:{x}:{y},scale={r.w}:{r.h},setsar=1[camraw{i}]")
        if scene.template == "floating_facecam":
            mask = workdir / "cam_mask.png"
            raster.cam_mask(r.w, scene.regions.cam.shape).save(mask)
            m = add_image(mask)
            g.append(f"{m}format=gray[cm{i}]")
            g.append(f"[camraw{i}]format=rgba[camrgba{i}]")
            g.append(f"[camrgba{i}][cm{i}]alphamerge[cam{i}]")
        else:
            g.append(f"[camraw{i}]copy[cam{i}]")
        g.append(f"{base}[cam{i}]overlay={r.x}:{r.y}:shortest=1[b1_{i}]")
        base = f"[b1_{i}]"

    moments = [m for m in fx.moments if 0 <= m < d]
    chain = []
    if fx.color == "vivid":
        chain.append("eq=saturation=1.22:contrast=1.05")
    elif fx.color == "cinematic":
        chain.append("eq=saturation=1.1:contrast=1.12:brightness=-0.02")
        chain.append("colorbalance=rs=-0.04:bs=0.06:rh=0.06:bh=-0.05")
    if chain:
        g.append(f"{base}{','.join(chain)}[graded]")
        base = "[graded]"

    frame = raster.frame_image(scene)
    if frame is not None:
        fpath = workdir / "frame.png"
        frame.save(fpath)
        f = add_image(fpath)
        g.append(f"{base}{f}overlay=0:0:shortest=1[framed]")
        base = "[framed]"
    if fx.speed_lines and moments:
        spath = workdir / "speed_lines.png"
        raster.speed_lines().save(spath)
        s = add_image(spath)
        g.append(f"{base}{s}overlay=0:0:enable='{_windows(moments, 0.45)}':shortest=1[speed]")
        base = "[speed]"

    if scene.captions.visible and words:
        ass = workdir / "captions.ass"
        ass.write_text(
            captions.build_ass(
                words, settings=scene.captions.model_dump(), keywords=keywords, duration=d
            ),
            encoding="utf-8",
        )
        g.append(f"{base}subtitles=filename={ass.name}[capt]")
        base = "[capt]"

    for i, ly in enumerate(scene.layers):
        if not ly.visible or ly.start >= d:
            continue
        end = min(d, ly.end) if ly.end is not None else d
        if end - ly.start < 0.05:
            continue
        if ly.kind == "image":
            src = image_path(ly.asset_id or "")
            if src is None:
                continue
            img = raster.render_image_layer(ly, src)
        else:
            text = fill_text(ly.text, values)
            if not text:
                continue
            img = raster.render_text_layer(ly, text)
        lpath = workdir / f"layer_{i:02d}.png"
        img.save(lpath)
        inp = add_image(lpath)
        f_chain = ["format=rgba"]
        a_in = ALPHA_IN.get(ly.anim_in, 0.2)  # slides fade in over 0.2 s
        if a_in > 0:
            f_chain.append(f"fade=t=in:st={ly.start:.3f}:d={a_in}:alpha=1")
        if ly.anim_out == "fade" and ly.end is not None and end - ly.start > 0.4:
            f_chain.append(f"fade=t=out:st={end - 0.25:.3f}:d=0.25:alpha=1")
        sexpr, mx = _scale_expr(ly)
        pw, ph = img.width, img.height
        if sexpr:
            pw, ph = compose._even(img.width * mx + 4), compose._even(img.height * mx + 4)
            f_chain.append(
                f"scale=w='max(2,trunc(iw*({sexpr})/2)*2)':h='max(2,trunc(ih*({sexpr})/2)*2)'"
                ":eval=frame"
            )
            f_chain.append(
                f"pad=w={pw}:h={ph}:x='(ow-iw)/2':y='(oh-ih)/2':color=0x00000000:eval=frame"
            )
        g.append(f"{inp}{','.join(f_chain)}[l{i}]")
        dx, dy = _offset_exprs(ly)
        cx, cy = round(ly.x * W - pw / 2), round(ly.y * H - ph / 2)
        g.append(
            f"{base}[l{i}]overlay=x='{cx}+{dx}':y='{cy}+{dy}':eval=frame:"
            f"enable='between(t,{ly.start:.3f},{end:.3f})':shortest=1[o{i}]"
        )
        base = f"[o{i}]"

    post = []
    if fx.shake and moments:
        k = _decay(moments, 0.35)
        post.append(
            f"crop=w={W - 48}:h={H - 48}:x='24+18*sin(75*t)*({k})':y='24+14*sin(61*t+1)*({k})',"
            f"scale={W}:{H}"
        )
    if fx.flash and moments:
        post.append(f"eq=brightness='0.3*({_decay(moments, 0.15)})':eval=frame")
    if fx.glitch and moments:
        post.append(f"rgbashift=rh=14:bh=-14:enable='{_windows(moments, 0.12)}'")
    post.append("format=yuv420p")
    g.append(f"{base}{','.join(post)}[v]")
    g.append(f"[0:a]{audio_chain(plan.measured)}[a]")
    return Built(";\n".join(g), inputs)


def render_scene(
    edited: Path,
    scene: Scene,
    plan: CutPlan,
    out: Path,
    *,
    words: list[CaptionWord],
    keywords: list[str],
    values: dict[str, str | None],
    image_path: Callable[[str], Path | None],
    on_progress: Callable[[float], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    workdir = out.parent
    built = build_graph(
        scene, plan, workdir, words=words, keywords=keywords, values=values, image_path=image_path
    )
    gfile = workdir / f"{out.stem}.graph.txt"
    gfile.write_text(built.graph, encoding="utf-8")
    ffmpeg.run_ffmpeg(
        [
            "-i",
            str(edited),
            *[a for inp in built.inputs for a in inp],
            "-/filter_complex",
            gfile.name,
            "-map",
            "[v]",
            "-map",
            "[a]",
            *compose.video_encoder(),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            "-t",
            f"{plan.duration:.3f}",
            out.name,
        ],
        duration_s=plan.duration,
        on_progress=on_progress,
        is_cancelled=is_cancelled,
        cwd=workdir,
    )


def peak_time(plan: CutPlan) -> float:
    return plan.zoom_peaks[0] if plan.zoom_peaks else plan.duration / 2
