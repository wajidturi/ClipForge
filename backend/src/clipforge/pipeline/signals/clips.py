"""Twitch viewer clips of a VOD via the official Helix API (your own app credentials).

Viewers clip what they found worth sharing; each clip has a `vod_offset`. This needs
a free Twitch developer app (client id + secret) in Settings; without it the step
is skipped. Uses app access tokens (client credentials), read-only.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

import httpx

from clipforge.pipeline.signals import Spike

HELIX = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"  # noqa: S105 - an endpoint, not a secret


class TwitchApiError(RuntimeError):
    pass


def _token(client: httpx.Client, client_id: str, secret: str) -> str:
    r = client.post(
        TOKEN_URL,
        params={
            "client_id": client_id,
            "client_secret": secret,
            "grant_type": "client_credentials",
        },
    )
    if r.status_code != 200:
        raise TwitchApiError(f"Twitch rejected the app credentials ({r.status_code})")
    return str(r.json()["access_token"])


def _duration_s(text: str) -> float:
    """Helix durations look like '3h2m10s'."""
    total, num = 0.0, ""
    for ch in text:
        if ch.isdigit():
            num += ch
        else:
            total += int(num or 0) * {"h": 3600, "m": 60, "s": 1}.get(ch, 0)
            num = ""
    return total


def vod_clips(
    video_id: str,
    client_id: str,
    secret: str,
    *,
    transport: httpx.BaseTransport | None = None,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    vid = video_id.removeprefix("v")
    with httpx.Client(transport=transport, timeout=20) as c:
        token = _token(c, client_id, secret)
        h = {"Client-Id": client_id, "Authorization": f"Bearer {token}"}
        r = c.get(f"{HELIX}/videos", params={"id": vid}, headers=h)
        if r.status_code != 200 or not r.json().get("data"):
            raise TwitchApiError(f"VOD {vid} not found on Twitch ({r.status_code})")
        video = r.json()["data"][0]
        started = datetime.fromisoformat(video["created_at"].replace("Z", "+00:00"))
        ended = started + timedelta(seconds=_duration_s(video.get("duration", "")) + 60)
        params: dict[str, Any] = {
            "broadcaster_id": video["user_id"],
            "started_at": started.isoformat().replace("+00:00", "Z"),
            "ended_at": ended.isoformat().replace("+00:00", "Z"),
            "first": 100,
        }
        clips: list[dict[str, Any]] = []
        for _ in range(max_pages):
            r = c.get(f"{HELIX}/clips", params=params, headers=h)
            if r.status_code != 200:
                raise TwitchApiError(f"clip list failed ({r.status_code})")
            body = r.json()
            clips += [
                x
                for x in body.get("data", [])
                if x.get("video_id") == vid and x.get("vod_offset") is not None
            ]
            cursor = (body.get("pagination") or {}).get("cursor")
            if not cursor:
                break
            params["after"] = cursor
        return clips


def clip_spikes(clips: list[dict[str, Any]], start: float, end: float) -> list[Spike]:
    out: list[Spike] = []
    for c in clips:
        s = float(c["vod_offset"])
        e = s + float(c.get("duration") or 30)
        if e < start or s > end:
            continue
        views = int(c.get("view_count") or 0)
        out.append(
            Spike(
                "clip",
                s,
                e,
                min(1.0, math.log10(views + 1) / 4),  # 10k views ~ full score
                f"clipped · {views:,} views",
                {"views": views, "title": c.get("title"), "url": c.get("url")},
            )
        )
    return out
