"""Classify a user-supplied link: which platform, which video id.

This is a fast, offline first pass used for validation and duplicate detection
before anything is downloaded. yt-dlp's metadata later confirms the final id.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit, urlunsplit

from clipforge.db.enums import Platform


class InvalidSourceError(ValueError):
    """The input cannot be used as a source (bad scheme, private address, playlist...)."""


@dataclass(frozen=True)
class ResolvedUrl:
    platform: Platform
    external_id: str
    url: str  # normalised URL
    id_is_guess: bool = False  # True when we fell back to a hash of the URL


# host suffix -> platform
HOSTS: list[tuple[str, Platform]] = [
    ("youtube.com", Platform.youtube),
    ("youtu.be", Platform.youtube),
    ("twitch.tv", Platform.twitch),
    ("kick.com", Platform.kick),
    ("tiktok.com", Platform.tiktok),
    ("twitter.com", Platform.x),
    ("x.com", Platform.x),
    ("instagram.com", Platform.instagram),
    ("facebook.com", Platform.facebook),
    ("fb.watch", Platform.facebook),
    ("rumble.com", Platform.rumble),
    ("vimeo.com", Platform.vimeo),
    ("reddit.com", Platform.reddit),
    ("redd.it", Platform.reddit),
    ("dailymotion.com", Platform.dailymotion),
    ("dai.ly", Platform.dailymotion),
]

YT_ID = r"([A-Za-z0-9_-]{11})"

# (platform, regex on "host+path?query"); first capture group = id, optional prefix
PATTERNS: list[tuple[Platform, re.Pattern[str], str]] = [
    (Platform.youtube, re.compile(rf"youtu\.be/{YT_ID}"), ""),
    (Platform.youtube, re.compile(rf"youtube\.com/(?:shorts|live|embed|v)/{YT_ID}"), ""),
    (Platform.youtube, re.compile(rf"youtube\.com/watch\?(?:.*&)?v={YT_ID}"), ""),
    (Platform.twitch, re.compile(r"twitch\.tv/videos/(\d+)"), "v"),
    (Platform.twitch, re.compile(r"clips\.twitch\.tv/([A-Za-z0-9_-]+)"), "clip:"),
    (Platform.twitch, re.compile(r"twitch\.tv/[^/]+/clip/([A-Za-z0-9_-]+)"), "clip:"),
    (Platform.kick, re.compile(r"kick\.com/[^/]+/videos/([0-9a-f-]{36})"), ""),
    (Platform.kick, re.compile(r"kick\.com/video/([0-9a-f-]{36})"), ""),
    (Platform.kick, re.compile(r"kick\.com/[^/]+/clips/([A-Za-z0-9_-]+)"), "clip:"),
    (Platform.tiktok, re.compile(r"tiktok\.com/@[^/]+/video/(\d+)"), ""),
    (Platform.x, re.compile(r"(?:twitter|x)\.com/[^/]+/status/(\d+)"), ""),
    (Platform.instagram, re.compile(r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)"), ""),
    (Platform.facebook, re.compile(r"facebook\.com/.*?(?:videos|reel)/(\d+)"), ""),
    (Platform.facebook, re.compile(r"facebook\.com/watch/?\?(?:.*&)?v=(\d+)"), ""),
    (Platform.rumble, re.compile(r"rumble\.com/(v[0-9a-z]+)-"), ""),
    (Platform.rumble, re.compile(r"rumble\.com/embed/(v[0-9a-z]+)"), ""),
    (Platform.vimeo, re.compile(r"vimeo\.com/(?:video/)?(\d+)"), ""),
    (Platform.reddit, re.compile(r"reddit\.com/r/[^/]+/comments/([a-z0-9]+)"), ""),
    (Platform.reddit, re.compile(r"redd\.it/([a-z0-9]+)"), ""),
    (Platform.dailymotion, re.compile(r"dailymotion\.com/video/([a-z0-9]+)"), ""),
    (Platform.dailymotion, re.compile(r"dai\.ly/([a-z0-9]+)"), ""),
]

# Links that point at many videos or at a channel, not at one video.
LISTS = [
    re.compile(r"youtube\.com/(?:playlist|@[^/]+/?$|@[^/]+/(?:videos|streams|shorts)|channel/|c/)"),
    re.compile(r"twitch\.tv/[^/]+/videos/?$"),
]


def _platform_for(host: str) -> Platform:
    host = host.lower().removeprefix("www.").removeprefix("m.")
    for suffix, platform in HOSTS:
        if host == suffix or host.endswith("." + suffix):
            return platform
    return Platform.other


def _reject_private(host: str) -> None:
    """Block links to this machine or the local network (would let a page probe the LAN)."""
    if host in {"localhost", ""} or host.endswith(".local") or host.endswith(".localhost"):
        raise InvalidSourceError("links to this computer or the local network are not allowed")
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        if "." not in host:  # single-label names ("nope", "nas") are LAN hosts or typos
            raise InvalidSourceError(
                "that does not look like a link; paste a full video URL"
            ) from None
        return
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        raise InvalidSourceError("links to this computer or the local network are not allowed")


def normalise(url: str) -> str:
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def resolve_url(raw: str) -> ResolvedUrl:
    if not raw or not raw.strip():
        raise InvalidSourceError("paste a link to a video")
    url = normalise(raw)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise InvalidSourceError("only http(s) links are supported")
    host = (parts.hostname or "").lower()
    _reject_private(host)
    platform = _platform_for(host)
    target = (
        host.removeprefix("www.").removeprefix("m.")
        + parts.path
        + ("?" + parts.query if parts.query else "")
    )
    for p, rx, prefix in PATTERNS:
        if p == platform and (m := rx.search(target)):
            return ResolvedUrl(platform, prefix + m.group(1), url)
    # youtube list links with a video id inside: take the video, drop the list
    if platform == Platform.youtube and (v := parse_qs(parts.query).get("v")):
        return ResolvedUrl(platform, v[0], url)
    for rx in LISTS:
        if rx.search(target):
            raise InvalidSourceError(
                "this link is a channel or playlist; paste the link of one video"
            )
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    return ResolvedUrl(platform, f"url:{digest}", url, id_is_guess=True)


def platform_from_extractor(extractor_key: str | None, fallback: Platform) -> Platform:
    """Map yt-dlp's extractor name (e.g. 'Youtube', 'TwitchVod') to our platform."""
    key = (extractor_key or "").lower()
    for name in (p.value for p in Platform if p not in (Platform.other, Platform.file)):
        if key.startswith(name) or (name == "x" and key.startswith("twitter")):
            return Platform(name)
    return fallback
