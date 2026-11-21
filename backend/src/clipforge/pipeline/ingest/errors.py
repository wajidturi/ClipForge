"""Turn raw download errors into a short message plus a concrete fix."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Explained:
    message: str
    hint: str | None
    retryable: bool


RULES: list[tuple[re.Pattern[str], str, str | None, bool]] = [
    (
        re.compile(r"sign in to confirm|not a bot|confirm your age|age-restricted", re.I),
        "The site asked for a sign-in or bot check.",
        "Wait 10 minutes and retry, or set 'Use cookies from browser' (e.g. firefox) in "
        "Settings / CF_YTDLP_COOKIES_BROWSER.",
        False,
    ),
    (
        re.compile(
            r"private video|members[- ]only|requires? (a )?subscription|login required", re.I
        ),
        "This video is private or for members only.",
        "Use a public video, or one your browser account can watch with cookies enabled.",
        False,
    ),
    (
        re.compile(r"video unavailable|has been removed|does not exist|404", re.I),
        "The video is unavailable or was removed.",
        "Check the link in a browser.",
        False,
    ),
    (
        re.compile(r"unsupported url", re.I),
        "This site or link type is not supported.",
        "Paste the link of a single video page.",
        False,
    ),
    (
        re.compile(r"HTTP Error 429|too many requests|rate.?limit", re.I),
        "The site is rate-limiting downloads.",
        "Retry later; the job retries automatically with a delay.",
        True,
    ),
    (
        re.compile(r"geo.?restrict|not available in your country", re.I),
        "The video is blocked in your country.",
        None,
        False,
    ),
    (
        re.compile(
            r"timed? ?out|connection (reset|refused|aborted)|temporary failure|getaddrinfo", re.I
        ),
        "Network problem while downloading.",
        "Check the internet connection; the job retries automatically.",
        True,
    ),
    (
        re.compile(r"ffmpeg not found|ffprobe not found|ffmpeg is not installed", re.I),
        "FFmpeg is missing.",
        "Windows: winget install Gyan.FFmpeg, then restart ClipForge.",
        False,
    ),
    (
        re.compile(r"requested format is not available|no video formats", re.I),
        "No downloadable format was offered for this video.",
        "Update the downloader: clipforge update-downloader",
        False,
    ),
]


def explain(raw: str) -> Explained:
    text = re.sub(r"\x1b\[[0-9;]*m", "", raw or "")  # strip colour codes
    for rx, msg, hint, retryable in RULES:
        if rx.search(text):
            return Explained(msg, hint, retryable)
    first = text.strip().splitlines()[0] if text.strip() else "Unknown error"
    return Explained(first.removeprefix("ERROR: ")[:300], None, True)
