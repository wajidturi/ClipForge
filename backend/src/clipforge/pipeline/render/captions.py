"""Word-by-word captions and the hook banner as an ASS subtitle file (burned by libass).

Styles are data (`STYLES`), so adding one is a dictionary entry. Modes:
- highlight : a group of words, the spoken word in the highlight colour
- single    : one big word at a time with a small pop
- karaoke   : the group fills with colour as it is spoken (\\kf)
- plain     : the group only, no highlight
Keywords (from the pick) stay in the keyword colour (green) in every style.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from clipforge.pipeline.render.edl import CaptionWord

W, H = 1080, 1920


def ass_color(rgb: str, alpha: int = 0) -> str:
    """'#RRGGBB' -> '&HAABBGGRR' (alpha 0 = opaque)."""
    r, g, b = rgb[1:3], rgb[3:5], rgb[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _font(windows: str, other: str) -> str:
    return windows if sys.platform == "win32" else other


@dataclass(frozen=True)
class Style:
    name: str
    label: str
    font: str
    size: int
    color: str = "#FFFFFF"
    highlight: str = "#FFE135"
    keyword: str = "#3DDC84"
    outline_color: str = "#000000"
    outline: float = 6
    shadow: float = 0
    box: str | None = None  # opaque box colour behind the text
    upper: bool = True
    group: int = 3
    mode: str = "highlight"


STYLES: dict[str, Style] = {
    "classic": Style(
        "classic", "Classic (white caps, yellow word)", _font("Arial Black", "DejaVu Sans"), 78
    ),
    "word": Style(
        "word",
        "One word (big, punchy)",
        _font("Impact", "DejaVu Sans"),
        132,
        outline=9,
        group=1,
        mode="single",
        highlight="#FFFFFF",
    ),
    "box": Style(
        "box",
        "Box (text on a colour block)",
        _font("Arial Black", "DejaVu Sans"),
        70,
        color="#FFFFFF",
        highlight="#111111",
        box="#7C5CFF",
        outline=14,
        group=3,
    ),
    "karaoke": Style(
        "karaoke",
        "Karaoke (fills as spoken)",
        _font("Arial Black", "DejaVu Sans"),
        74,
        color="#FFFFFF",
        highlight="#FFE135",
        mode="karaoke",
    ),
    "minimal": Style(
        "minimal",
        "Minimal (small, lower)",
        _font("Segoe UI", "DejaVu Sans"),
        58,
        outline=2,
        shadow=2,
        upper=False,
        group=5,
        mode="plain",
    ),
}
DEFAULT_STYLE = "classic"


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(text: str) -> str:
    return re.sub(r"[{}\\]", "", text).replace("\n", " ").strip()


def _norm(word: str) -> str:
    return re.sub(r"[^\w']", "", word).upper()


@dataclass(frozen=True)
class Group:
    words: tuple[CaptionWord, ...]
    start: float
    end: float


def group_words(words: list[CaptionWord], size: int, *, max_gap: float = 0.6) -> list[Group]:
    groups: list[list[CaptionWord]] = []
    for w in words:
        cur = groups[-1] if groups else None
        if (
            cur is None
            or len(cur) >= size
            or w.start - cur[-1].end > max_gap
            or cur[-1].text.rstrip().endswith((".", "?", "!"))
        ):
            groups.append([w])
        else:
            cur.append(w)
    out: list[Group] = []
    for i, g in enumerate(groups):
        nxt = groups[i + 1][0].start if i + 1 < len(groups) else g[-1].end + 0.6
        out.append(Group(tuple(g), g[0].start, min(nxt, g[-1].end + 0.6)))
    return out


def _word_text(w: CaptionWord, style: Style) -> str:
    t = _clean(w.text)
    return t.upper() if style.upper else t


def _colored(text: str, color: str) -> str:
    return f"{{\\c{ass_color(color)}}}{text}{{\\c{ass_color('#FFFFFF')}}}"


def build_ass(
    words: list[CaptionWord],
    *,
    style: str = DEFAULT_STYLE,
    keywords: list[str] | None = None,
    hook: str | None = None,
    hook_s: float = 3.0,
    margin_v: int = 520,
    duration: float | None = None,
    size: tuple[int, int] = (W, H),
) -> str:
    """`size` must equal the video size: libass stretches PlayRes to the frame, so a
    1080x1920 script on a 1080x1350 video would squash the text."""
    st = STYLES.get(style, STYLES[DEFAULT_STYLE])
    kw = {_norm(k) for k in keywords or [] if k.strip()}
    box = st.box is not None
    cap_style = (
        f"Style: Cap,{st.font},{st.size},{ass_color(st.color)},{ass_color(st.color)},"
        f"{ass_color(st.box or st.outline_color)},{ass_color(st.box or '#000000', 0x60)},"
        f"-1,0,0,0,100,100,0,0,{3 if box else 1},{st.outline},{st.shadow},2,80,80,{margin_v},1"
    )
    hook_style = (
        f"Style: Hook,{_font('Arial Black', 'DejaVu Sans')},76,{ass_color('#111111')},"
        f"{ass_color('#111111')},{ass_color('#FFFFFF')},{ass_color('#FFFFFF')},"
        "-1,0,0,0,100,100,0,0,3,18,0,8,90,90,190,1"
    )
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {size[0]}",
        f"PlayResY: {size[1]}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        cap_style,
        hook_style,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if hook:
        end = min(hook_s, duration) if duration else hook_s
        lines.append(
            f"Dialogue: 1,{_ts(0)},{_ts(end)},Hook,,0,0,0,,{{\\fad(0,250)}}{_clean(hook).upper()}"
        )

    def colour_of(w: CaptionWord) -> str | None:
        return st.keyword if _norm(w.text) in kw else None

    for g in group_words(words, st.group):
        if st.mode == "single":
            for i, w in enumerate(g.words):
                end = g.words[i + 1].start if i + 1 < len(g.words) else g.end
                text = _word_text(w, st)
                if c := colour_of(w):
                    text = _colored(text, c)
                pop = "{\\fscx118\\fscy118\\t(0,90,\\fscx100\\fscy100)}"
                lines.append(f"Dialogue: 0,{_ts(w.start)},{_ts(end)},Cap,,0,0,0,,{pop}{text}")
        elif st.mode == "karaoke":
            parts = []
            for i, w in enumerate(g.words):
                nxt = g.words[i + 1].start if i + 1 < len(g.words) else w.end
                cs = max(1, round((nxt - w.start) * 100))
                text = _word_text(w, st)
                fill = colour_of(w) or st.highlight
                parts.append(f"{{\\kf{cs}\\1c{ass_color(fill)}\\2c{ass_color(st.color)}}}{text}")
            lines.append(f"Dialogue: 0,{_ts(g.start)},{_ts(g.end)},Cap,,0,0,0,," + " ".join(parts))
        elif st.mode == "plain":
            text = " ".join(
                _colored(_word_text(w, st), c) if (c := colour_of(w)) else _word_text(w, st)
                for w in g.words
            )
            lines.append(f"Dialogue: 0,{_ts(g.start)},{_ts(g.end)},Cap,,0,0,0,,{text}")
        else:  # highlight
            for i, cur in enumerate(g.words):
                a = g.start if i == 0 else cur.start
                b = g.words[i + 1].start if i + 1 < len(g.words) else g.end
                parts = []
                for w in g.words:
                    t = _word_text(w, st)
                    if w is cur:
                        parts.append(_colored(t, st.highlight))
                    elif c := colour_of(w):
                        parts.append(_colored(t, c))
                    else:
                        parts.append(t)
                lines.append(f"Dialogue: 0,{_ts(a)},{_ts(b)},Cap,,0,0,0,," + " ".join(parts))
    return "\n".join(lines) + "\n"


def coverage(words: list[CaptionWord], ass_text: str) -> float:
    """Share of spoken words that appear in some caption event (QC)."""
    if not words:
        return 1.0
    events = " ".join(
        re.sub(r"\{[^}]*\}", "", line.split(",", 9)[-1]).upper()
        for line in ass_text.splitlines()
        if line.startswith("Dialogue:") and ",Cap," in line
    )
    found = sum(
        1 for w in words if _norm(w.text) and _norm(w.text) in re.sub(r"[^\w' ]", " ", events)
    )
    return found / len(words)
