"""Chat replay: when chat suddenly types much faster than usual, something happened.

Sources: yt-dlp downloads YouTube live-chat replays ("live_chat") and Twitch VOD chat
("rechat") as subtitle files; we parse both formats. A spike is a 10 s bin whose
message rate is >= `ratio` x the rolling baseline and >= `min_per_min`. Chat reacts
late, so spikes are shifted earlier by `lag_s` when they become moments.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from clipforge.pipeline.signals import Spike, merge_runs
from clipforge.pipeline.signals.audio import rolling_median


@dataclass(frozen=True)
class ChatMessage:
    t: float  # seconds into the video
    author: str
    text: str


# ------------------------------------------------------------------ parsers
def _yt_text(renderer: dict[str, Any]) -> str:
    runs = (renderer.get("message") or {}).get("runs") or []
    parts = []
    for r in runs:
        if "text" in r:
            parts.append(r["text"])
        elif "emoji" in r:  # custom emotes: use their shortcut, e.g. :yt:
            sc = (r["emoji"].get("shortcuts") or [""])[0]
            parts.append(sc or r["emoji"].get("emojiId", ""))
    return "".join(parts)


def parse_youtube_live_chat(path: Path) -> list[ChatMessage]:
    """yt-dlp's .live_chat.json: one JSON object per line."""
    out: list[ChatMessage] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            replay = obj.get("replayChatItemAction") or {}
            offset = replay.get("videoOffsetTimeMsec")
            if offset is None:
                continue
            for action in replay.get("actions") or []:
                item = (action.get("addChatItemAction") or {}).get("item") or {}
                r = item.get("liveChatTextMessageRenderer") or item.get(
                    "liveChatPaidMessageRenderer"
                )
                if not r:
                    continue
                author = ((r.get("authorName") or {}).get("simpleText")) or ""
                out.append(ChatMessage(int(offset) / 1000, author, _yt_text(r)))
    return out


def parse_twitch_rechat(path: Path) -> list[ChatMessage]:
    """Twitch VOD chat as saved by yt-dlp. Accepts the classic v5 shape
    ({"comments": [...content_offset_seconds...]}) and the GQL shape (edges/node)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = []
    if isinstance(data, dict):
        items = data.get("comments") or data.get("edges") or []
    elif isinstance(data, list):
        for d in data:
            if isinstance(d, dict) and "comments" in d:
                items.extend(d["comments"])
            else:
                items.append(d)
    out: list[ChatMessage] = []
    for c in items:
        c = c.get("node", c) if isinstance(c, dict) else {}
        t = c.get("content_offset_seconds", c.get("contentOffsetSeconds"))
        if t is None:
            continue
        msg = c.get("message") or {}
        text = msg.get("body") or "".join(
            (f.get("text") or "") for f in (msg.get("fragments") or [])
        )
        who = c.get("commenter") or {}
        author = who.get("display_name") or who.get("displayName") or ""
        out.append(ChatMessage(float(t), author, text))
    return out


def parse_chat_file(path: Path) -> list[ChatMessage]:
    name = path.name.lower()
    msgs = parse_youtube_live_chat(path) if "live_chat" in name else parse_twitch_rechat(path)
    return sorted(msgs, key=lambda m: m.t)


# ------------------------------------------------------------------ analysis
BOT_NAMES = {
    "nightbot",
    "streamelements",
    "streamlabs",
    "moobot",
    "fossabot",
    "wizebot",
    "sery_bot",
}
# ":emote_name:" shortcuts count as one token; then words; then symbol runs like "??".
_WORD = re.compile(r":[\w-]+:|[\w']+|[^\w\s]{2,}", re.UNICODE)


def is_spam(m: ChatMessage) -> bool:
    return m.author.lower() in BOT_NAMES or m.text.startswith("!") or "http" in m.text.lower()


def rate_per_min(msgs: list[ChatMessage], start: float, end: float, bin_s: float) -> np.ndarray:
    n = max(1, int(np.ceil((end - start) / bin_s)))
    counts = np.zeros(n, dtype=np.float32)
    for m in msgs:
        i = int((m.t - start) // bin_s)
        if 0 <= i < n:
            counts[i] += 1
    return counts * (60.0 / bin_s)


def top_phrases(msgs: list[ChatMessage], k: int = 3) -> list[str]:
    """Most repeated tokens/emotes (one vote per message), e.g. ['KEKW', 'W', 'LMAO']."""
    c: Counter[str] = Counter()
    for m in msgs:
        c.update({t.upper() if len(t) <= 6 else t for t in _WORD.findall(m.text)})
    return [w for w, n in c.most_common(k * 3) if n >= 2][:k]


def chat_spikes(
    msgs: list[ChatMessage],
    start: float,
    end: float,
    *,
    bin_s: float = 10.0,
    baseline_s: float = 300.0,
    ratio: float = 3.0,
    min_per_min: float = 15.0,
    lag_s: float = 8.0,
) -> tuple[list[Spike], np.ndarray]:
    """Returns spikes and the per-bin rate (messages/min) for the timeline."""
    clean = [m for m in msgs if not is_spam(m) and start <= m.t <= end]
    rate = rate_per_min(clean, start, end, bin_s)
    if len(rate) == 0 or not clean:
        return [], rate
    base = rolling_median(rate, max(3, int(baseline_s / bin_s)))
    base = np.maximum(base, 1.0)
    flags = list((rate >= ratio * base) & (rate >= min_per_min))
    out: list[Spike] = []
    for s, e in merge_runs(flags, bin_s, start):
        i0, i1 = int((s - start) / bin_s), int((e - start) / bin_s)
        peak_ratio = float(np.max(rate[i0:i1] / base[i0:i1]))
        peak_rate = float(np.max(rate[i0:i1]))
        window = [m for m in clean if s <= m.t < e]
        phrases = top_phrases(window)
        # chat types a few seconds after the moment: move the range earlier
        out.append(
            Spike(
                "chat_spike",
                max(start, s - lag_s),
                max(start, e - lag_s),
                min(1.0, peak_ratio / (2 * ratio)),
                f"chat x{peak_ratio:.1f}" + (f" {phrases[0]}" if phrases else ""),
                {
                    "ratio": round(peak_ratio, 1),
                    "rate_per_min": round(peak_rate),
                    "top": phrases,
                    "samples": [m.text for m in window[:5]],
                },
            )
        )
    return out, rate
