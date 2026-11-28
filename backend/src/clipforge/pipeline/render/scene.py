"""The *scene*: everything about how a Short looks, as one JSON document.

A scene = template + its geometry (regions, frame, facecam, divider) + captions +
effects + a list of layers (text, badges/stickers, emojis, images such as a logo).
The renderer (``compose.scene_graph``) and the browser preview
(``frontend/src/features/studio/compositor.ts``) both draw from it with the same
rules, so the studio preview matches the exported MP4.

Coordinates: positions are fractions (0..1) of the canvas; sizes are pixels on the
*design canvas*, whose short side is always 1080 (9:16 -> 1080x1920, 16:9 -> 1920x1080).
The video is drawn at the design size and scaled to the chosen output size at the end,
so text and frames keep their proportions at any size. Times are seconds of the Short.

Template elements are ordinary layers with a ``role`` (``hook``, ``reaction``,
``name`` ...), so users can move, restyle or hide them. Text may use the
placeholders ``{hook}``, ``{title}``, ``{channel}``, ``{reaction}``.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clipforge.pipeline.render.captions import STYLES
from clipforge.pipeline.render.fonts import DEFAULT_FONT, FONTS

W, H = 1080, 1920
SCENE_VERSION = 1
Color = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")]
TemplateId = Literal[
    "streamer_first", "gameplay_first", "dual_vision", "floating_facecam", "cinematic"
]
TEMPLATE_IDS: tuple[str, ...] = (
    "streamer_first",
    "gameplay_first",
    "dual_vision",
    "floating_facecam",
    "cinematic",
)
LEGACY_LAYOUT = {  # Phase 5 layouts -> templates (old versions, old API calls)
    "stack": "streamer_first",
    "bubble": "floating_facecam",
    "crop": "cinematic",
    "full": "cinematic",
}
Anim = Literal["none", "fade", "pop", "zoom", "slide_up", "slide_down", "slide_left", "slide_right"]
Loop = Literal["none", "pulse", "shake", "float"]
Shape = Literal["none", "box", "pill", "tag", "ribbon", "burst"]


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ------------------------------------------------------------------ parts
class Frame(_M):
    style: Literal["neon", "solid", "none"] = "neon"
    color: Color = "#8B5CF6"
    color2: Color = "#22D3EE"
    width: int = Field(6, ge=0, le=20)
    radius: int = Field(34, ge=0, le=80)
    glow: int = Field(18, ge=0, le=40)
    gap: int = Field(14, ge=0, le=48)  # space around/between panels
    background: Color = "#0B0A14"


class Cam(_M):
    """Floating facecam (template ``floating_facecam``)."""

    x: float = Field(0.27, ge=0, le=1)
    y: float = Field(0.78, ge=0, le=1)
    size: float = Field(0.38, ge=0.15, le=0.7)  # fraction of the width
    shape: Literal["circle", "rounded", "square"] = "circle"
    border_color: Color = "#A78BFA"
    border_width: int = Field(8, ge=0, le=24)
    glow: int = Field(22, ge=0, le=40)
    visible: bool = True


class Divider(_M):
    style: Literal["ribbon", "bar", "line", "none"] = "ribbon"
    color: Color = "#7C3AED"
    color2: Color = "#22D3EE"
    thickness: int = Field(96, ge=4, le=160)
    tilt: float = Field(4, ge=-12, le=12)  # degrees; positive rises to the right


CamBackground = Literal[
    "original",
    "blur_soft",
    "blur_strong",
    "neon_purple",
    "cyber_blue",
    "sunset",
    "midnight",
    "studio_gray",
    "red_rush",
    "aurora",
    "gold_lux",
]
CAM_BACKGROUNDS: dict[str, str] = {  # id -> name, in picker order
    "original": "Original",
    "blur_soft": "Soft blur",
    "blur_strong": "Strong blur",
    "neon_purple": "Neon purple",
    "cyber_blue": "Cyber blue",
    "sunset": "Sunset",
    "midnight": "Midnight",
    "studio_gray": "Studio",
    "red_rush": "Red rush",
    "aurora": "Aurora",
    "gold_lux": "Gold",
}
BLUR_BACKGROUNDS = {"blur_soft": 10, "blur_strong": 26}  # box blur radius at 1080 wide


class Spot(_M):
    """A panel placed freely in the studio (dragged / resized), as fractions of the
    video: top-left corner and size. It may reach past the edges (cropped there)."""

    x: float = Field(0.0, ge=-0.9, le=0.9)
    y: float = Field(0.0, ge=-0.9, le=0.9)
    w: float = Field(1.0, ge=0.1, le=1.5)
    h: float = Field(1.0, ge=0.1, le=1.5)


class Place(_M):
    """Free layout: where the gameplay and the facecam panel sit, overriding the
    template's arrangement (None = the template's own place)."""

    game: Spot | None = None
    cam: Spot | None = None


class Regions(_M):
    place: Place | None = None  # free layout from the studio (drag to move / resize)
    split: float = Field(0.42, ge=0.25, le=0.75)  # height share of the top panel
    frame: Frame = Field(default_factory=Frame)
    cam: Cam = Field(default_factory=Cam)
    divider: Divider = Field(default_factory=Divider)
    fit: Literal["fill", "blur"] = "fill"  # full-screen templates: crop or whole picture
    cam_bg: CamBackground = "blur_soft"  # behind the streamer (needs the person cut-out)
    cam_enhance: bool = True  # denoise + sharpen + clarity on the (small, upscaled) facecam


class Captions(_M):
    visible: bool = True
    preset: str = "classic"
    font: str = DEFAULT_FONT
    size: int = Field(80, ge=28, le=180)
    color: Color = "#FFFFFF"
    highlight: Color = "#FFE135"
    keyword: Color = "#3DDC84"
    outline_color: Color = "#000000"
    outline: float = Field(6, ge=0, le=20)
    box: Color | None = None
    upper: bool = True
    words: int = Field(3, ge=1, le=6)
    mode: Literal["highlight", "single", "karaoke", "plain"] = "highlight"
    y: float = Field(0.7, ge=0.08, le=0.95)  # centre of the caption line
    animation: Literal["none", "pop"] = "pop"


class Effects(_M):
    zoom_punch: bool = True
    zoom_amount: float = Field(0.10, ge=0.0, le=0.25)
    shake: bool = False
    flash: bool = False
    glitch: bool = False
    speed_lines: bool = False
    vignette: bool = False
    letterbox: bool = False
    color: Literal["none", "vivid", "hdr", "cinematic"] = "hdr"
    moments: list[float] = Field(default_factory=list, max_length=12)  # effect times (s)


class Layer(_M):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    kind: Literal["text", "emoji", "image"] = "text"
    role: str | None = None  # template element this came from
    name: str = ""
    visible: bool = True
    x: float = Field(0.5, ge=-0.2, le=1.2)
    y: float = Field(0.5, ge=-0.2, le=1.2)
    scale: float = Field(1.0, ge=0.2, le=4)
    rotation: float = Field(0, ge=-45, le=45)
    opacity: float = Field(1, ge=0, le=1)
    start: float = Field(0, ge=0)
    end: float | None = None  # None = until the end
    anim_in: Anim = "pop"
    anim_out: Literal["none", "fade"] = "fade"
    loop: Loop = "none"
    # text / emoji
    text: str = Field("", max_length=160)
    font: str = DEFAULT_FONT
    size: int = Field(80, ge=12, le=400)
    color: Color = "#FFFFFF"
    stroke_color: Color = "#000000"
    stroke: int = Field(6, ge=0, le=30)
    shadow: bool = True
    italic: bool = False
    upper: bool = True
    max_width: float = Field(0.86, ge=0.2, le=1)
    shape: Shape = "none"
    shape_color: Color = "#7C3AED"
    shape_stroke: Color | None = None
    # image
    asset_id: str | None = None
    width: float = Field(0.25, ge=0.03, le=1)  # fraction of the frame width

    @field_validator("font")
    @classmethod
    def _known_font(cls, v: str) -> str:
        return v if v in FONTS else DEFAULT_FONT


CanvasPreset = Literal["9:16", "4:5", "1:1", "16:9", "4:3", "custom"]
CANVAS_PRESETS: dict[str, tuple[int, int, str]] = {  # id -> (width, height, label)
    "9:16": (1080, 1920, "Shorts · Reels · TikTok"),
    "4:5": (1080, 1350, "Instagram feed"),
    "1:1": (1080, 1080, "Square"),
    "16:9": (1920, 1080, "YouTube · landscape"),
    "4:3": (1440, 1080, "Classic landscape"),
}
CANVAS_MIN, CANVAS_MAX = 240, 3840
CANVAS_MAX_RATIO = 4.0  # longest side at most 4x the shortest


class Canvas(_M):
    """Output size of the video: one of the presets, or any width x height."""

    preset: CanvasPreset = "9:16"
    w: int = Field(1080, ge=CANVAS_MIN, le=CANVAS_MAX)
    h: int = Field(1920, ge=CANVAS_MIN, le=CANVAS_MAX)

    @model_validator(mode="after")
    def _fit(self) -> Canvas:
        if self.preset != "custom":
            self.w, self.h = CANVAS_PRESETS[self.preset][:2]
        self.w, self.h = self.w // 2 * 2, self.h // 2 * 2  # video encoders need even sizes
        if max(self.w, self.h) > CANVAS_MAX_RATIO * min(self.w, self.h):
            raise ValueError(f"width and height may differ by at most {CANVAS_MAX_RATIO:g}x")
        return self


class Scene(_M):
    v: int = SCENE_VERSION
    template: TemplateId = "streamer_first"
    regions: Regions = Field(default_factory=Regions)
    captions: Captions = Field(default_factory=Captions)
    effects: Effects = Field(default_factory=Effects)
    layers: list[Layer] = Field(default_factory=list, max_length=40)
    canvas: Canvas = Field(default_factory=Canvas)


def design_size(scene: Scene) -> tuple[int, int]:
    """The canvas everything is drawn on: the output shape with its short side 1080."""
    w, h = scene.canvas.w, scene.canvas.h
    k = 1080 / min(w, h)
    return even(w * k), even(h * k)


def is_landscape(scene: Scene) -> bool:
    w, h = design_size(scene)
    return w > h


# ------------------------------------------------------------------ templates
@dataclass(frozen=True)
class TemplateInfo:
    id: str
    name: str
    tagline: str
    description: str
    needs_cam: bool
    controls: tuple[str, ...]  # which template settings the studio shows


TEMPLATES: dict[str, TemplateInfo] = {
    "streamer_first": TemplateInfo(
        "streamer_first",
        "Streamer First",
        "Facecam on top, gameplay below",
        "The classic reaction layout: the streamer's face is the star, the game tells the story.",
        True,
        ("split", "frame"),
    ),
    "gameplay_first": TemplateInfo(
        "gameplay_first",
        "Gameplay First",
        "Big gameplay, facecam below",
        "Action first: most of the screen for the game, the reaction underneath.",
        True,
        ("split", "frame"),
    ),
    "dual_vision": TemplateInfo(
        "dual_vision",
        "Dual Vision",
        "Even split with a divider",
        "Balanced view: streamer and game share the screen, joined by a bold divider.",
        True,
        ("split", "frame", "divider"),
    ),
    "floating_facecam": TemplateInfo(
        "floating_facecam",
        "Floating Facecam",
        "Full gameplay, facecam bubble",
        "Full-screen gameplay with a small, movable facecam bubble.",
        True,
        ("cam", "fit"),
    ),
    "cinematic": TemplateInfo(
        "cinematic",
        "Cinematic Gaming",
        "Full screen with effects",
        "Full-screen footage with impact text, flashes, shakes and speed lines on big moments.",
        False,
        ("fit", "effects"),
    ),
}


@dataclass
class Ctx:
    """Facts about the cut a default scene is built for."""

    duration: float
    peaks: list[float]
    has_cam: bool = True  # a facecam or people were found (else the panel shows the action)
    cam_kind: str = "overlay"  # overlay | camera | action (see cuts.cam_boxes)


def _peak(ctx: Ctx, i: int = 0, fallback: float = 1.5) -> float:
    p = sorted(ctx.peaks)
    t = p[i] if len(p) > i else fallback
    return round(min(max(0.6, t - 0.25), max(0.6, ctx.duration - 2.0)), 2)


def _t(
    text: str,
    *,
    role: str,
    name: str,
    x: float,
    y: float,
    size: int,
    **kw: Any,
) -> Layer:
    return Layer(kind="text", role=role, name=name, text=text, x=x, y=y, size=size, **kw)


def caption_preset(preset: str, **over: Any) -> Captions:
    st = STYLES.get(preset, STYLES["classic"])
    base = Captions(
        preset=st.name,
        font=st.font_id,
        size=st.size,
        color=st.color,
        highlight=st.highlight,
        keyword=st.keyword,
        outline_color=st.outline_color,
        outline=st.outline,
        box=st.box,
        upper=st.upper,
        words=st.group,
        mode=st.mode,
    )
    return base.model_copy(update=over)


def caption_presets() -> dict[str, dict[str, Any]]:
    return {k: caption_preset(k).model_dump() for k in STYLES}


def default_scene(template: str, ctx: Ctx) -> Scene:
    """Attractive defaults: frames, captions, effects and template elements."""
    template = template if template in TEMPLATES else "streamer_first"
    end = round(ctx.duration, 2)
    p0, p1 = _peak(ctx, 0), _peak(ctx, 1, fallback=ctx.duration * 0.6)
    hook = dict(start=0.0, end=min(end, 3.2), anim_in="pop", anim_out="fade")

    if template == "streamer_first":
        return Scene(
            template="streamer_first",
            regions=Regions(split=0.42),
            captions=caption_preset("gaming", y=0.66),
            effects=Effects(zoom_punch=True, flash=True, moments=ctx.peaks[:3]),
            layers=[
                _t(
                    "● LIVE",
                    role="live",
                    name="Live badge",
                    x=0.13,
                    y=0.045,
                    size=40,
                    font="segoe_black",
                    shape="tag",
                    shape_color="#EF4444",
                    stroke=0,
                    shadow=False,
                    anim_in="fade",
                    anim_out="none",
                ),
                _t(
                    "{reaction}",
                    role="reaction",
                    name="Reaction caption",
                    x=0.76,
                    y=0.2,
                    size=84,
                    color="#FFE135",
                    rotation=-8,
                    shape="burst",
                    shape_color="#111111",
                    shape_stroke="#FFE135",
                    stroke=4,
                    start=p0,
                    end=min(end, p0 + 2.4),
                    anim_in="pop",
                    loop="shake",
                    max_width=0.4,
                ),
                _t(
                    "{channel}",
                    role="name",
                    name="Streamer name",
                    x=0.2,
                    y=0.385,
                    size=40,
                    font="segoe_black",
                    shape="pill",
                    shape_color="#7C3AED",
                    stroke=0,
                    anim_in="slide_right",
                    anim_out="none",
                    max_width=0.5,
                ),
                _t(
                    "{hook}",
                    role="hook",
                    name="Hook (big title)",
                    x=0.5,
                    y=0.86,
                    size=104,
                    color="#FFE135",
                    italic=True,
                    stroke=9,
                    rotation=-4,
                    **hook,
                ),
            ],
        )
    if template == "gameplay_first":
        return Scene(
            template="gameplay_first",
            regions=Regions(split=0.62, frame=Frame(color="#22D3EE", color2="#8B5CF6")),
            captions=caption_preset("box", y=0.53),
            effects=Effects(zoom_punch=True, shake=True, moments=ctx.peaks[:3]),
            layers=[
                _t(
                    "💀 {hook}",
                    role="hook",
                    name="Kill banner",
                    x=0.5,
                    y=0.1,
                    size=86,
                    color="#FFFFFF",
                    shape="burst",
                    shape_color="#DC2626",
                    shape_stroke="#FDE047",
                    stroke=6,
                    rotation=-3,
                    max_width=0.8,
                    **hook,
                ),
                _t(
                    "+100",
                    role="score",
                    name="Score highlight",
                    x=0.78,
                    y=0.36,
                    size=70,
                    color="#FDE047",
                    stroke=6,
                    visible=False,
                    start=p0,
                    end=min(end, p0 + 2),
                    anim_in="slide_up",
                ),
                _t(
                    "{reaction}",
                    role="reaction",
                    name="Reaction caption",
                    x=0.3,
                    y=0.9,
                    size=74,
                    color="#FFFFFF",
                    italic=True,
                    shape="ribbon",
                    shape_color="#7C3AED",
                    stroke=4,
                    rotation=-6,
                    start=p0,
                    end=min(end, p0 + 2.6),
                    anim_in="slide_right",
                    max_width=0.55,
                ),
                _t(
                    "{channel}",
                    role="name",
                    name="Streamer name",
                    x=0.82,
                    y=0.665,
                    size=34,
                    font="segoe_black",
                    shape="pill",
                    shape_color="#0EA5E9",
                    stroke=0,
                    anim_in="fade",
                    anim_out="none",
                    max_width=0.4,
                ),
            ],
        )
    if template == "dual_vision":
        return Scene(
            template="dual_vision",
            regions=Regions(split=0.5, divider=Divider()),
            captions=caption_preset("word", y=0.78),
            effects=Effects(zoom_punch=True, flash=True, moments=ctx.peaks[:3]),
            layers=[
                _t(
                    "🎮 {hook}",
                    role="divider_label",
                    name="Divider label",
                    x=0.5,
                    y=0.5,
                    size=78,
                    color="#FFE135",
                    italic=True,
                    stroke=5,
                    rotation=-4,
                    start=0,
                    end=None,
                    anim_in="zoom",
                    anim_out="none",
                    max_width=0.9,
                ),
                _t(
                    "{channel}",
                    role="name",
                    name="Streamer name",
                    x=0.8,
                    y=0.05,
                    size=36,
                    font="segoe_black",
                    shape="pill",
                    shape_color="#111111",
                    shape_stroke="#A78BFA",
                    stroke=0,
                    anim_in="fade",
                    anim_out="none",
                ),
                _t(
                    "{reaction}",
                    role="reaction",
                    name="Reaction caption",
                    x=0.3,
                    y=0.4,
                    size=70,
                    color="#FFFFFF",
                    shape="burst",
                    shape_color="#DB2777",
                    stroke=4,
                    rotation=6,
                    start=p0,
                    end=min(end, p0 + 2.2),
                    anim_in="pop",
                    max_width=0.45,
                ),
            ],
        )
    if template == "floating_facecam":
        return Scene(
            template="floating_facecam",
            regions=Regions(cam=Cam(), frame=Frame(width=6, gap=0, radius=0)),
            captions=caption_preset("karaoke", y=0.58),
            effects=Effects(zoom_punch=True, moments=ctx.peaks[:3]),
            layers=[
                _t(
                    "{hook}",
                    role="hook",
                    name="Top title",
                    x=0.5,
                    y=0.12,
                    size=100,
                    color="#FFFFFF",
                    italic=True,
                    stroke=9,
                    rotation=-5,
                    max_width=0.9,
                    **hook,
                ),
                _t(
                    "{channel}",
                    role="name",
                    name="Streamer name",
                    x=0.66,
                    y=0.9,
                    size=40,
                    font="segoe_black",
                    shape="tag",
                    shape_color="#7C3AED",
                    stroke=0,
                    anim_in="slide_left",
                    anim_out="none",
                    max_width=0.5,
                ),
                _t(
                    "SUBSCRIBE 🔔",
                    role="subscribe",
                    name="Subscribe button",
                    x=0.7,
                    y=0.955,
                    size=40,
                    font="segoe_black",
                    shape="pill",
                    shape_color="#EF4444",
                    stroke=0,
                    start=max(0, end - 4),
                    end=None,
                    anim_in="pop",
                    loop="pulse",
                ),
                _t(
                    "{reaction}",
                    role="reaction",
                    name="Reaction caption",
                    x=0.62,
                    y=0.72,
                    size=66,
                    color="#FFE135",
                    stroke=6,
                    rotation=-6,
                    start=p0,
                    end=min(end, p0 + 2.2),
                    anim_in="pop",
                    visible=False,
                ),
            ],
        )
    # cinematic
    return Scene(
        template="cinematic",
        regions=Regions(fit="fill", frame=Frame(style="none", gap=0, radius=0)),
        captions=caption_preset("classic", y=0.62),
        effects=Effects(
            zoom_punch=True,
            zoom_amount=0.14,
            shake=True,
            flash=True,
            glitch=True,
            speed_lines=True,
            vignette=True,
            color="cinematic",
            moments=ctx.peaks[:3],
        ),
        layers=[
            _t(
                "💀 {hook}",
                role="hook",
                name="Cinematic title",
                x=0.5,
                y=0.17,
                size=92,
                color="#FFFFFF",
                shape="burst",
                shape_color="#B91C1C",
                shape_stroke="#FCA5A5",
                stroke=6,
                rotation=-4,
                max_width=0.85,
                **hook,
            ),
            _t(
                "{reaction}",
                role="impact",
                name="Impact word",
                x=0.5,
                y=0.8,
                size=130,
                color="#FFE135",
                italic=True,
                stroke=10,
                rotation=-6,
                start=p1,
                end=min(end, p1 + 2.6),
                anim_in="zoom",
                loop="shake",
                max_width=0.95,
            ),
            _t(
                "{channel}",
                role="name",
                name="Streamer name",
                x=0.5,
                y=0.93,
                size=36,
                font="segoe_black",
                shape="pill",
                shape_color="#1F1B2E",
                shape_stroke="#A78BFA",
                stroke=0,
                anim_in="fade",
                anim_out="none",
            ),
        ],
    )


USER_ROLES = (None, "logo", "user")  # layers that survive a template switch


def _captions_customised(scene: Scene) -> bool:
    """Did the user change the captions from what the template started with?"""
    base = default_scene(scene.template, Ctx(10.0, [])).captions
    ignore = {"y"}
    return scene.captions.model_dump(exclude=ignore) != base.model_dump(exclude=ignore)


def switch_template(scene: Scene, template: str, ctx: Ctx) -> Scene:
    """New template defaults, keeping what the user added (logos, own text, emojis).
    Captions the user changed are kept; untouched ones take the new template's look."""
    new = default_scene(template, ctx)
    new.canvas = scene.canvas.model_copy()
    keep = [ly for ly in scene.layers if ly.role in USER_ROLES]
    new.layers += keep
    if _captions_customised(scene):
        new.captions = scene.captions.model_copy(update={"y": new.captions.y})
    return new


def resolve_template(
    requested: str | None, has_cam: bool, kind: str = "overlay"
) -> tuple[str, str | None]:
    """(template used, note). The chosen template is always used; ``auto`` picks one:
    Streamer First for facecam overlays, Cinematic for people on camera or no people.
    With no facecam or people, a facecam panel shows a close-up of the action."""
    t = LEGACY_LAYOUT.get(requested or "", requested or "auto")
    if t not in TEMPLATES:
        t = "streamer_first" if has_cam and kind == "overlay" else "cinematic"
    if TEMPLATES[t].needs_cam and not has_cam:
        return t, "No facecam or people found, so the facecam panel shows a close-up of the action"
    return t, None


# ------------------------------------------------------------------ text
PLACEHOLDER = re.compile(r"\{(hook|title|channel|reaction)\}")


def fill_text(text: str, values: dict[str, str | None]) -> str:
    return PLACEHOLDER.sub(lambda m: (values.get(m.group(1)) or "").strip(), text).strip()


# ------------------------------------------------------------------ geometry
@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


def even(v: float) -> int:
    return max(2, round(v) // 2 * 2)


def panels(scene: Scene) -> dict[str, Rect]:
    """Where the game and the facecam are drawn (output pixels).

    Stacked templates: two panels inset by the frame gap, top/bottom on portrait and
    square canvases, side by side (first one on the left) on landscape ones.
    Full-screen templates: the game fills the frame; the floating cam is a square.
    """
    r, t = scene.regions, scene.template
    W, H = design_size(scene)  # noqa: N806
    g = r.frame.gap if r.frame.style != "none" else 0
    if t in ("streamer_first", "gameplay_first", "dual_vision"):
        if W > H:
            left_w = even(W * r.split)
            first = Rect(g, g, even(left_w - g - g / 2), even(H - 2 * g))
            second = Rect(even(left_w + g / 2), g, even(W - left_w - g - g / 2), even(H - 2 * g))
        else:
            top_h = even(H * r.split)
            first = Rect(g, g, even(W - 2 * g), even(top_h - g - g / 2))
            second = Rect(g, even(top_h + g / 2), even(W - 2 * g), even(H - top_h - g - g / 2))
        out = (
            {"game": first, "cam": second}
            if t == "gameplay_first"
            else {"cam": first, "game": second}
        )
    else:
        out = {"game": Rect(g, g, even(W - 2 * g), even(H - 2 * g))}
        if t == "floating_facecam" and r.cam.visible:
            side = even(min(W, H) * r.cam.size)
            out["cam"] = Rect(
                round(r.cam.x * W - side / 2), round(r.cam.y * H - side / 2), side, side
            )
    pl = r.place
    if pl is not None:  # moved / resized in the studio
        if pl.game is not None:
            out["game"] = spot_rect(pl.game, W, H)
        # the floating cam has its own position (regions.cam)
        if pl.cam is not None and "cam" in out and t != "floating_facecam":
            out["cam"] = spot_rect(pl.cam, W, H)
    return out


def spot_rect(sp: Spot, w: int, h: int) -> Rect:
    return Rect(round(sp.x * w), round(sp.y * h), max(16, even(sp.w * w)), max(16, even(sp.h * h)))


def free_layout(scene: Scene) -> bool:
    """Has the user moved a panel? (the template's divider no longer fits then)"""
    pl = scene.regions.place
    return pl is not None and (pl.game is not None or pl.cam is not None)


TILE_GAP = 8  # px between people sharing the facecam panel
CAM_MAX_GROW = 1.3  # facecam crops: see cover_crop


def cam_tiles(rect: Rect, n: int, gap: int = TILE_GAP) -> list[Rect]:
    """Split the facecam panel into n tiles (one per streamer): side by side, or one
    above the other when the panel is taller than wide (landscape layouts)."""
    if n <= 1:
        return [rect] if n == 1 else []
    if rect.h > rect.w:
        h = even((rect.h - gap * (n - 1)) / n)
        rows = [Rect(rect.x, rect.y + i * (h + gap), rect.w, h) for i in range(n - 1)]
        last_y = rect.y + (n - 1) * (h + gap)
        return [*rows, Rect(rect.x, last_y, rect.w, even(rect.y + rect.h - last_y))]
    w = even((rect.w - gap * (n - 1)) / n)
    out = [Rect(rect.x + i * (w + gap), rect.y, w, rect.h) for i in range(n - 1)]
    last_x = rect.x + (n - 1) * (w + gap)
    return [*out, Rect(last_x, rect.y, even(rect.x + rect.w - last_x), rect.h)]


def cover_crop(
    box: tuple[float, float, float, float],
    aspect: float,
    src_w: int,
    src_h: int,
    max_grow: float | None = None,
) -> tuple[int, int, int, int]:
    """Source crop (x, y, w, h px) of aspect w/h around a normalised box, covering it.

    With ``max_grow`` the crop may exceed the box by at most that factor on the side
    that has to grow; beyond it, the other side is cut instead (a narrow facecam tile
    zooms in on the face rather than pulling in what sits above or below the cam)."""
    bx, by, bw, bh = box
    cw, ch = bw * src_w, bh * src_h
    if cw / ch < aspect:
        if max_grow and ch * aspect > cw * max_grow:
            cw = cw * max_grow
            ch = cw / aspect
        else:
            cw = ch * aspect
    elif max_grow and cw / aspect > ch * max_grow:
        ch = ch * max_grow
        cw = ch * aspect
    else:
        ch = cw / aspect
    if cw > src_w:
        cw, ch = src_w, src_w / aspect
    if ch > src_h:
        ch, cw = src_h, src_h * aspect
    cx, cy = (bx + bw / 2) * src_w, (by + bh / 2) * src_h
    x = min(max(cx - cw / 2, 0), src_w - cw)
    y = min(max(cy - ch / 2, 0), src_h - ch)
    return int(x), int(y), even(cw), even(ch)
